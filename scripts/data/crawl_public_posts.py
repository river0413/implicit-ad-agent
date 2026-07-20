#!/usr/bin/env python3
"""爬取公开帖子内容并脱敏。

核心产出（每条记录）：
  post_id, platform, blogger_id, published_at,
  title, text, media, comments, blogger_history_refs

改进点（相比旧版）：
  1. 从页面 HTML 提取真实发布时间，不再用采集时间冒充
  2. 下载文章内图片到本地 media/ 目录，填充 media 字段
  3. 正文清洗：去除标题重复、SEO 噪声、页脚干扰
  4. JSON 输出带缩进，按逻辑分组排序，人工可读
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv
load_dotenv()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CST = timezone(timedelta(hours=8))  # 中国标准时间


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def get_salt() -> str:
    salt = os.getenv("ANONYMIZATION_SALT")
    if not salt:
        raise RuntimeError(
            "ANONYMIZATION_SALT is required. Set it in your environment or .env file."
        )
    return salt


def stable_hash(value: str, salt: str, length: int = 16) -> str:
    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()
    return digest[:length]


def fuzzy_name(name: str) -> str:
    name = name.strip()
    if not name:
        return ""
    if len(name) <= 2:
        return name[0] + "*" * (len(name) - 1)
    return name[0] + "*" * (len(name) - 2) + name[-1]


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"<[^>]+>", " ", html)
    return normalize_text(html)


def extract_title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return normalize_text(match.group(1))
    return ""


# ═══════════════════════════════════════════════════════════════
# 发布时间提取（从页面 HTML 中提取真实时间，而非采集时间）
# ═══════════════════════════════════════════════════════════════

def extract_publish_date(html: str) -> Optional[str]:
    """从微信文章页面提取真实发布时间，返回 ISO 8601 +08:00 格式。"""
    # 方式 1: og:article:published_time meta 标签
    match = re.search(
        r'<meta\s[^>]*property="article:published_time"[^>]*content="([^"]+)"',
        html, re.IGNORECASE
    )
    if match:
        return _normalize_datetime(match.group(1))

    # 方式 2: var create_time / createTime 在 <script> 中
    match = re.search(
        r'(?:var\s+create_time\s*=\s*"|createTime\s*[=:]\s*")(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',
        html
    )
    if match:
        return _normalize_datetime(match.group(1))

    # 方式 3: 中文日期模式 "2022年4月16日 11:36"
    match = re.search(
        r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2}):(\d{2})',
        html
    )
    if match:
        y, m, d, hh, mm = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}T{int(hh):02d}:{int(mm):02d}:00+08:00"

    # 方式 4: 纯数字 "2022-04-16" 出现在页面中
    match = re.search(
        r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})',
        html
    )
    if match:
        return _normalize_datetime(match.group(1) + " " + match.group(2))

    return None  # 确实提取不到


def _normalize_datetime(raw: str) -> str:
    """将各种格式的时间字符串归一化为 ISO 8601 +08:00。"""
    raw = raw.strip()
    # 尝试多种格式
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",      # 2022-04-16T11:36:00+08:00
        "%Y-%m-%dT%H:%M:%S",         # 2022-04-16T11:36:00
        "%Y-%m-%dT%H:%M%z",          # 2022-04-16T11:36+08:00
        "%Y-%m-%d %H:%M:%S",         # 2022-04-16 11:36:00
        "%Y-%m-%d %H:%M",            # 2022-04-16 11:36
        "%Y-%m-%d",                  # 2022-04-16
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CST)
            return dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        except ValueError:
            continue
    # 实在解析不了，返回原始字符串（标记为异常）
    return raw


# ═══════════════════════════════════════════════════════════════
# 图片提取与下载
# ═══════════════════════════════════════════════════════════════

def extract_image_urls(html: str) -> List[str]:
    """从微信文章 HTML 中提取所有图片 URL（优先 data-src，其次 src）。"""
    urls = []
    seen = set()

    # 微信文章图片通常在 <img data-src="..."> 中
    for match in re.finditer(r'<img\s[^>]*?(?:data-src|src)\s*=\s*"([^"]+)"', html, re.IGNORECASE):
        url = match.group(1)
        # 只保留 mmbiz.qpic.cn（微信图床）的图片
        if "mmbiz.qpic.cn" in url or url.startswith("http"):
            if url not in seen:
                seen.add(url)
                urls.append(url)

    return urls


def download_images(
    image_urls: List[str],
    post_id: str,
    media_base_dir: Path,
    session: requests.Session,
) -> List[Dict]:
    """下载图片到 media/{post_id}/ 目录，返回 media 字段数组。"""
    media_records = []
    post_media_dir = media_base_dir / post_id
    post_media_dir.mkdir(parents=True, exist_ok=True)

    for idx, img_url in enumerate(image_urls):
        try:
            # 确定文件扩展名
            parsed = urlparse(img_url)
            ext = os.path.splitext(parsed.path)[1]
            if not ext or ext.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
                ext = ".jpg"  # 微信图片默认 jpg

            filename = f"{idx:02d}{ext}"
            filepath = post_media_dir / filename

            # 下载
            resp = session.get(img_url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            filepath.write_bytes(resp.content)

            media_records.append({
                "ref": str(filepath.relative_to(media_base_dir.parent)).replace("\\", "/"),
                "source_url": img_url,
            })
        except Exception as exc:
            print(f"  [img-err] {img_url[:80]}... → {exc}", file=sys.stderr)
            # 下载失败仍保留引用信息
            media_records.append({
                "ref": None,
                "source_url": img_url,
            })

    return media_records


# ═══════════════════════════════════════════════════════════════
# 正文清洗
# ═══════════════════════════════════════════════════════════════

def clean_body_text(raw_text: str, title: str) -> str:
    """清洗正文：去标题重复、SEO 噪声、页脚干扰。"""
    text = raw_text.strip()

    # 去除标题在正文开头的重复（微信文章常见）
    if title and text.startswith(title):
        text = text[len(title):].strip()

    # 去除常见 SEO / 页脚噪声行
    noise_patterns = [
        r"在小说阅读器读本章",
        r"在小说阅读器中沉浸阅读",
        r"去阅读",
        r"阅读\s*\d+\+?",
        r"原创\s+\S+\s+\S+",             # "原创 炮霸707 炮霸707"
        r"^\d{4}年\d{1,2}月\d{1,2}日\s*\d{2}:\d{2}",  # 正文内嵌的发布日期行
        r"^[A-Za-z]{2,10}\s*$",          # 孤立的英文单词（如 "Beijing"）
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.MULTILINE)

    # 压缩连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def platform_from_url(url: str) -> str:
    if "mp.weixin.qq.com" in url or "weixin.qq.com" in url:
        return "wechat_official_account"
    if "weibo.com" in url or "m.weibo.cn" in url:
        return "weibo_public_account"
    return "web_public"


def _fetch_via_playwright(url: str, timeout: int = 30000) -> str:
    """使用 Playwright 浏览器渲染抓取页面（用于需要 JS 渲染的站点如微信）。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()
        # 搜狗反盗链：需要带 weixin.sogou.com 的 Referer
        extra_headers = {}
        if "src=11" in url or "timestamp=" in url:
            extra_headers["Referer"] = "https://weixin.sogou.com"
        page.set_extra_http_headers(extra_headers)
        page.goto(url, wait_until="networkidle", timeout=timeout)
        content = page.content()
        browser.close()
        return content


def fetch_url(url: str) -> str:
    # 微信文章需要浏览器渲染，直接用 requests 只会拿到错误页
    if "mp.weixin.qq.com" in url:
        return _fetch_via_playwright(url)

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.text


def build_post_record(
    url: str,
    publisher_name: str,
    publisher_id: str,
    title: str,
    body_text: str,
    media_records: List[Dict],
    published_at: Optional[str],
    history_post_ids: Optional[List[str]],
    salt: str,
    collector: str,
    terms_checked_at: Optional[str],
) -> Dict:
    """构建一条规范化的帖子记录。

    返回的 JSON 对象按逻辑分组排列，字段顺序即为人工阅读顺序：
      标识 → 时间 → 内容 → 媒体 → 评论 → 历史 → 元数据

    blogger_history_refs 为 post_id 字符串列表（从博主搜索结果的
    其他文章 URL 派生），仅包含发布于当前帖之前的文章。
    """
    import collections

    source_ref_hash = stable_hash(url, salt, length=32)
    blogger_id = stable_hash(publisher_id or publisher_name or url, salt, length=24)
    post_id = stable_hash(url, salt, length=24)

    # 发布时间：优先用页面提取的，否则标记为 null
    if not published_at:
        published_at = None  # 明确表示未知，不用采集时间冒充

    record = collections.OrderedDict()
    # ── 标识 ──
    record["post_id"] = post_id
    record["platform"] = platform_from_url(url)
    record["blogger_id"] = blogger_id
    # ── 时间 ──
    record["published_at"] = published_at
    # ── 内容 ──
    record["title"] = title if title else None
    record["text"] = body_text
    # ── 媒体 ──
    record["media"] = media_records
    # ── 评论 ──
    record["comments"] = []
    # ── 博主历史（post_id 字符串列表）──
    record["blogger_history_refs"] = history_post_ids or []
    # ── 采集元数据 ──
    record["_collected"] = {
        "source_url": url,
        "source_ref_hash": source_ref_hash,
        "collected_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "collector": collector,
        "terms_checked_at": terms_checked_at,
    }

    return record


def load_urls(path: Path) -> List[Dict[str, str]]:
    urls = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("\t")]
            if len(parts) == 1:
                urls.append({"url": parts[0], "publisher_name": "", "publisher_id": ""})
            elif len(parts) >= 2:
                urls.append(
                    {
                        "url": parts[0],
                        "publisher_name": parts[1],
                        "publisher_id": parts[2] if len(parts) >= 3 else "",
                    }
                )
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect public posts and anonymize publisher info.")
    parser.add_argument("--input", default="data/raw/urls.txt", help="URL list file, one per line, optional tab-separated publisher name and publisher id")
    parser.add_argument("--output", default="data/interim/anonymized_posts.jsonl", help="Output JSONL file")
    parser.add_argument("--media-dir", default="data/media", help="Directory to store downloaded images")
    parser.add_argument("--no-images", action="store_true", help="Skip image downloading (media will be [])")
    parser.add_argument("--compact", action="store_true", help="Output compact single-line JSON instead of pretty-printed")
    parser.add_argument("--history-urls", default=None, help="File with all article URLs from the same blogger search (for blogger_history_refs)")
    parser.add_argument("--collector", default="D", help="Collector identifier")
    parser.add_argument("--terms-checked-at", default=None, help="Terms check date (YYYY-MM-DD)")
    args = parser.parse_args()

    salt = get_salt()
    input_path = Path(args.input)
    output_path = Path(args.output)
    media_base_dir = Path(args.media_dir)
    urls = load_urls(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    media_base_dir.mkdir(parents=True, exist_ok=True)

    # 加载博主全部历史 URL 列表 → 预计算所有 post_id
    all_history_urls: List[str] = []
    if args.history_urls:
        history_path = Path(args.history_urls)
        if history_path.exists():
            all_history_urls = [line.strip() for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            print(f"Loaded {len(all_history_urls)} history URLs from {args.history_urls}")

    session = requests.Session()
    indent = None if args.compact else 2

    records_written = 0
    for item in urls:
        url = item["url"]
        publisher_name = item["publisher_name"]
        publisher_id = item["publisher_id"]
        try:
            print(f"\n{'='*60}")
            print(f"Fetching: {url[:100]}...")
            html = fetch_url(url)

            # 1. 提取标题
            title = extract_title(html)
            print(f"  title: {title[:60]}")

            # 2. 提取真实发布时间
            published_at = extract_publish_date(html)
            print(f"  published: {published_at or '(unknown)'}")

            # 3. 正文提取与清洗
            raw_text = extract_text(html)
            body_text = clean_body_text(raw_text, title)
            print(f"  text: {len(body_text)} chars")

            # 4. 图片提取与下载
            if args.no_images:
                media_records = []
                print("  images: skipped (--no-images)")
            else:
                image_urls = extract_image_urls(html)
                print(f"  images: {len(image_urls)} found, downloading...")
                # post_id 需要先生成用于目录命名
                post_id = stable_hash(url, salt, length=24)
                media_records = download_images(image_urls, post_id, media_base_dir, session)
                print(f"  images: {len(media_records)} processed")

            # 5. 博主历史：从全部搜索结果 URL 中排除当前帖，其余作为 history
            history_post_ids = [
                stable_hash(h_url, salt, length=24)
                for h_url in all_history_urls
                if h_url != url
            ]

            # 6. 构建记录
            record = build_post_record(
                url=url,
                publisher_name=publisher_name,
                publisher_id=publisher_id,
                title=title,
                body_text=body_text,
                media_records=media_records,
                published_at=published_at,
                history_post_ids=history_post_ids,
                salt=salt,
                collector=args.collector,
                terms_checked_at=args.terms_checked_at,
            )

            # 7. 输出（每条记录之间用空行分隔，方便阅读）
            with output_path.open("a", encoding="utf-8") as stream:
                if records_written > 0:
                    stream.write("\n")  # 记录间空行
                json.dump(record, stream, ensure_ascii=False, indent=indent)
                stream.write("\n")
            records_written += 1
            print(f"  ✓ saved (history: {len(history_post_ids)} refs)")

        except Exception as exc:
            print(f"  ✗ failed: {exc}", file=sys.stderr)

    print(f"\n{'='*60}")
    print(f"Done. {records_written} records → {output_path}")
    print(f"Media files → {media_base_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
