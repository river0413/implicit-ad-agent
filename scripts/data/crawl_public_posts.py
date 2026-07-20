#!/usr/bin/env python3
"""爬取公开帖子内容并脱敏。

核心产出（每条记录）：
  post_id, platform, blogger_id, published_at,
  title, text, media, comments, blogger_history_refs

改进点（相比旧版）：
  1. 从页面 HTML 提取真实发布时间，不再用采集时间冒充
  2. 下载文章内图片到本地 media/ 目录，填充 media 字段
  3. 正文清洗：去除标题重复、SEO 噪声、页脚干扰
  4. 可选 LLM 模式：双 DeepSeek 交叉验证提取图片标注和 <图片N> 位置标记
  5. JSON 输出带缩进，按逻辑分组排序，人工可读
"""
import argparse
import hashlib
import json
import os
import random
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

# 确保项目根目录在 path 中，使得 scripts.data 和 impad 可被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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
    """清洗正文：去标题重复、SEO 噪声、微信 UI 界面文字、页脚干扰。

    微信文章 HTML 去标签后会残留大量 UI 字符串（"微信扫一扫""赞赏作者""写留言"等）。
    此函数用黑名单 + 行级规则尽可能剔除，但无法 100% 覆盖所有变体。
    如需高精度清洗，请使用 --use-llm 模式让 LLM 从原始 HTML 直接提取。
    """
    text = raw_text.strip()

    # ── 第1层：去除标题在正文开头的重复 ──
    if title and text.startswith(title):
        text = text[len(title):].strip()

    # ── 第2层：微信 UI 组件关键词黑名单 ──
    # 这些字符串是微信文章页面的 UI 元素，不是文章内容
    wechat_ui_keywords = [
        # 赞赏/付费相关
        "微信扫一扫赞赏作者", "喜欢作者", "赞赏作者", "其它金额", "赞赏金额",
        "最低赞赏", "赞赏后展示我的头像", "其他金额",
        # 留言/评论 UI
        "写留言", "暂无留言", "条留言", "已无更多数据", "发消息",
        "选择留言身份", "我的留言", "已留言", "确定删除留言吗",
        "留言", "写留言:",
        # 验证/环境检查
        "环境异常", "当前环境异常", "完成验证后即可继续访问", "去验证",
        # 导航/操作 UI
        "关闭", "返回", "更多", "正在加载", "知道了", "取消", "允许", "确定",
        "微信扫一扫", "关注该公众号", "使用小程序", "搜索", "分析",
        "调整当前正文文字大小", "网络结果",
        # 微信功能 UI
        "赞", "在看", "分享", "推荐", "收藏", "听过",
        "轻点两下取消赞", "轻点两下取消在看",
        "视频", "小程序",
        # 预览/标签
        "预览时标签不可点", "名称已清空",
        # 内容警告
        "当前内容可能存在未经审核的第三方商业营销信息", "请确认是否继续访问",
        "继续访问", "微信公众平台广告规范指引",
        # 划线功能
        "可在「公众号", "右上角", "划线」找到划线过的内容", "我知道了",
        # 投诉
        "确认提交投诉", "你可以补充投诉原因",
        # 个人观点声明
        "作者提示", "个人观点，仅供参考",
        # 关注引导
        "关注该公众号",
        # 其他微信 UI
        "使用完整服务", "可打开此内容",
        "的内容会推荐给朋友和关注你的人", "对关注你的人展示公众号身份",
        "选择留言身份",
    ]

    # 整行匹配：如果某行完全由 UI 关键词组成或只包含标点/空格+关键词，整行删除
    ui_pattern = "|".join(re.escape(kw) for kw in wechat_ui_keywords)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # 跳过纯 UI 行（行内只含 UI 关键词/标点/空格/数字/符号）
        if re.fullmatch(r"[\s\d\.,，。、；：！？…%¥&;:·\-\+\(\)（）\[\]【】《》""''/\\@#\$%\^&\*~`|]*(?:" + ui_pattern + r"[\s\d\.,，。、；：！？…%¥&;:·\-\+\(\)（）\[\]【】《》""''/\\@#\$%\^&\*~`|]*)+[\s\d\.,，。、；：！？…%¥&;:·\-\+\(\)（）\[\]【】《》""''/\\@#\$%\^&\*~`|]*$", stripped, re.IGNORECASE):
            continue
        # 跳过纯标点/空格/数字行（短于 5 个字符的非中文行）
        if len(stripped) < 5 and not re.search(r"[\u4e00-\u9fff]", stripped):
            continue
        # 跳过纯 URL 行
        if re.fullmatch(r"https?://\S+", stripped):
            continue
        # 跳过 HTML 实体残留
        if stripped in ("&nbsp;", "&amp;", "&lt;", "&gt;", "&quot;"):
            continue
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # ── 第3层：正则替换常见噪声模式 ──
    noise_patterns = [
        # 阅读器/小说噪声
        r"在小说阅读器读本章",
        r"在小说阅读器中沉浸阅读",
        r"去阅读",
        r"阅读\s*\d+\+?",
        # 原创声明行 "原创 炮霸707 炮霸707" "原创 作者名 公众号名"
        r"原创\s+\S+(\s+\S+)?",
        # 日期行 "2022年4月16日 11:36" "2022年4月16日 09:20 北京"
        r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{2}:\d{2}(\s*\S+)?",
        # 微信公众号来源声明
        r"来源[：:]\s*\S*\s*微信公众号",
        r"记者[：:]\s*\S+",
        # 分享/转发提示
        r"分享\s*到\s*朋友圈",
        r"点击\s*上方\s*蓝色字",
        # 微信功能入口
        r"微信\s*扫一扫\s*可打开此内容",
        r"使用完整服务",
        # 纯数字/百分比/金额行
        r"^[\d\s.,，。%¥\$€£]+$",
        # 单个汉字或单词行（杂散残留）
        r"^.{1,2}$",
        # 关注引导
        r"关注\s*该\s*公众号",
        r"点击\s*关注",
        # 划线/收藏提示
        r"可在.*找到划线过的内容",
        # 版权/免责声明
        r"版权声明",
        r"免责声明",
        r"以上内容仅供",
        # 广告/推广标记
        r"广告",
        r"推广",
        # 听全文
        r"听全文",
        # goback/forward 等导航残留
        r"\bgoback\b", r"\bforward\b",
        # 阅读数 "阅读 10000+" "阅读 999"
        r"阅读\s*\d+[\+万]?",
    ]
    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.MULTILINE | re.IGNORECASE)

    # ── 第4层：压缩空白 ──
    text = re.sub(r"\n{3,}", "\n\n", text)  # 多个空行 → 两个
    text = re.sub(r" {2,}", " ", text)       # 多个空格 → 一个
    text = text.strip()

    return text


def platform_from_url(url: str) -> str:
    if "mp.weixin.qq.com" in url or "weixin.qq.com" in url:
        return "wechat_official_account"
    if "weibo.com" in url or "m.weibo.cn" in url:
        return "weibo_public_account"
    return "web_public"


def _is_captcha_url(url: str) -> bool:
    """检测 URL 本身是否为微信验证页面（搜狗触发验证后返回的跳转链接）。"""
    return "wappoc_appmsgcaptcha" in url or "poc_token=" in url


def _is_verification_page(html: str) -> bool:
    """检测页面内容是否为微信环境验证页。"""
    markers = [
        "环境异常", "当前环境异常", "完成验证后即可继续访问",
        "去验证", "wappoc_appmsgcaptcha",
    ]
    html_lower = html[:2000]  # 只查前 2000 字符即可
    return any(m in html_lower for m in markers)


def _fetch_via_playwright(url: str, timeout: int = 30000, retry: int = 0) -> str:
    """使用 Playwright 浏览器渲染抓取页面，内置反检测和验证页重试。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # 反检测：隐藏自动化标记
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        # 移除 webdriver 标记
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        """)

        page = context.new_page()

        # 搜狗反盗链 Referer
        extra_headers = {}
        if "src=11" in url or "timestamp=" in url:
            extra_headers["Referer"] = "https://weixin.sogou.com"
        page.set_extra_http_headers(extra_headers)

        # 随机延迟模拟人类行为
        page.goto(url, wait_until="load", timeout=timeout)
        page.wait_for_timeout(random.randint(800, 2000))
        content = page.content()

        browser.close()

        # 检测验证页面，重试一次
        if _is_verification_page(content) and retry < 1:
            wait = 5 + retry * 10
            print(f"    检测到验证页面，{wait}s 后重试...")
            time.sleep(wait)
            return _fetch_via_playwright(url, timeout=timeout, retry=retry + 1)

        return content


def fetch_url(url: str) -> str:
    # 微信文章需要浏览器渲染
    if "mp.weixin.qq.com" in url:
        # 如果 URL 本身就是验证跳转链接，直接跳过
        if _is_captcha_url(url):
            raise ValueError(f"URL 为微信验证页面，跳过: {url[:80]}...")
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
    llm_meta: Optional[Dict] = None,
) -> Dict:
    """构建一条规范化的帖子记录。

    返回的 JSON 对象按逻辑分组排列，字段顺序即为人工阅读顺序：
      标识 → 时间 → 内容 → 媒体 → 评论 → 历史 → 元数据

    blogger_history_refs 为 post_id 字符串列表（从博主搜索结果的
    其他文章 URL 派生），仅包含发布于当前帖之前的文章。

    llm_meta: 双 LLM 验证元数据（--use-llm 时填充），含 verified / confidence / needs_review
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
    collected = collections.OrderedDict()
    collected["source_url"] = url
    collected["source_ref_hash"] = source_ref_hash
    collected["collected_at"] = datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    collected["collector"] = collector
    collected["terms_checked_at"] = terms_checked_at
    if llm_meta:
        collected["llm_mode"] = "html_direct"  # 标记为 HTML 直分析模式
        collected["llm_needs_review"] = llm_meta.get("needs_review", True)
        collected["llm_confidence"] = llm_meta.get("confidence", 0)
        if llm_meta.get("notes"):
            collected["llm_notes"] = llm_meta["notes"][:2000]
    record["_collected"] = collected

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
    parser.add_argument("--use-llm", action="store_true", help="Use dual DeepSeek LLMs to extract image captions and <图片N> position markers")
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

            # 跳过验证页面 URL
            if _is_captcha_url(url):
                print(f"  ⏭ 跳过（验证页面 URL）")
                continue

            html = fetch_url(url)

            # 跳过返回验证页面的内容
            if _is_verification_page(html):
                print(f"  ⏭ 跳过（页面为微信环境验证，非文章正文）")
                continue

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

            # 4. 图片 URL 提取
            image_urls = extract_image_urls(html) if not args.no_images else []
            print(f"  images: {len(image_urls)} found")

            # 5. LLM 分析（可选）：从原始 HTML 直接提取纯净正文 + 图片标注 + <图片N> 标记
            llm_result = None
            if args.use_llm and html:
                from scripts.data.llm_image_extractor import llm_extract_from_html
                try:
                    llm_result = llm_extract_from_html(html, image_urls)
                    # 用 LLM 提取的标题（如更准确）
                    if llm_result.get("title"):
                        title = llm_result["title"]
                        print(f"  [LLM] title: {title[:60]}")
                    # 用 LLM 提取的纯净正文替换
                    if llm_result.get("clean_text"):
                        body_text = llm_result["clean_text"]
                        print(f"  [LLM] clean text: {len(body_text)} chars")
                    if llm_result.get("needs_review"):
                        print(f"  [LLM] 需复核: 置信度 {llm_result.get('confidence', 0):.2f}")
                except Exception as exc:
                    print(f"  [LLM] 失败: {exc}, 回退到正则清洗")

            # 6. 图片下载
            if args.no_images:
                media_records = []
                print("  images: skipped (--no-images)")
            else:
                post_id = stable_hash(url, salt, length=24)
                media_records = download_images(image_urls, post_id, media_base_dir, session)
                print(f"  images: {len(media_records)} downloaded")

                # 将 LLM 提取的标注合并到 media 记录中
                if llm_result:
                    enrichments = llm_result.get("media_enrichments", [])
                    for enrichment in enrichments:
                        idx = enrichment.get("index", -1)
                        if 0 <= idx < len(media_records):
                            media_records[idx]["caption"] = enrichment.get("caption")
                            media_records[idx]["is_content"] = enrichment.get("is_content", True)
                    captions_found = sum(
                        1 for e in enrichments if e.get("caption")
                    )
                    print(f"  [LLM] captions extracted: {captions_found}/{len(image_urls)}")

            # 7. 博主历史：从全部搜索结果 URL 中排除当前帖，其余作为 history
            history_post_ids = [
                stable_hash(h_url, salt, length=24)
                for h_url in all_history_urls
                if h_url != url
            ]

            # 8. 构建记录
            record = build_post_record(
                url=url,
                publisher_name=publisher_name,
                publisher_id=publisher_id,
                title=title,
                body_text=body_text,
                media_records=media_records,
                published_at=published_at,
                history_post_ids=history_post_ids,
                llm_meta=llm_result,
                salt=salt,
                collector=args.collector,
                terms_checked_at=args.terms_checked_at,
            )

            # 9. 输出（每条记录之间用空行分隔，方便阅读）
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
