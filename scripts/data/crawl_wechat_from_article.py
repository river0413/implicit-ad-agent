#!/usr/bin/env python3
"""
从单篇 mp.weixin.qq.com 文章 URL 推断公众号 __biz 并抓取该公众号历史文章列表（输出为 URL 列表文件）。

用法示例：
python scripts/data/crawl_wechat_from_article.py --url "https://mp.weixin.qq.com/s?__biz=xxxxx...&mid=..." --output data/raw/urls_from_article.txt

说明：脚本尽力在不登录的前提下获取文章列表，可能遇到反爬或跳转情况。若失败，可尝试在浏览器中打开该文章并提供页面 HTML（或 cookies），或在合规允许下使用带浏览器渲染的抓取方式。
"""
import argparse
import base64
import json
import random
import re
import time
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urljoin


def fetch_html_playwright(url: str, headless: bool = True, timeout: int = 30000) -> Optional[str]:
    """使用 Playwright 打开页面并返回渲染后的 HTML 内容（同步）。
    仅在用户已安装 Playwright 且允许使用浏览器渲染时调用。
    返回 None 表示 Playwright 不可用或加载失败。
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("Playwright 未安装。请运行: pip install playwright && playwright install")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout)
            content = page.content()
            try:
                browser.close()
            except Exception:
                pass
            return content
    except Exception as e:
        print(f"Playwright 渲染失败: {e}")
        return None

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}


def extract_biz_from_url(url: str) -> Optional[str]:
    qs = parse_qs(urlparse(url).query)
    if "__biz" in qs:
        return qs["__biz"][0]
    return None


def parse_cookies(cookies_arg: str) -> dict:
    """解析 cookies 字符串或文件路径，返回 {name: value} 字典。
    支持格式：'k1=v1; k2=v2'、Netscape cookie 文件、EditThisCookie JSON 文件、.env 文件。
    """
    import os as _os

    if not cookies_arg:
        return {}
    # 先尝试作为文件路径读取
    if _os.path.exists(cookies_arg):
        raw = Path(cookies_arg).read_text(encoding="utf-8").strip()
    else:
        raw = cookies_arg.strip()

    # JSON 格式（EditThisCookie 导出）
    if raw.startswith("[") and raw.endswith("]"):
        try:
            arr = json.loads(raw)
            return {
                c["name"]: c["value"]
                for c in arr
                if c.get("name") and c.get("value")
            }
        except Exception:
            pass

    # Netscape cookie 格式
    cookies: dict = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "k1=v1; k2=v2; k3=v3" 格式，支持多行
        for item in line.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            k, v = k.strip(), v.strip()
            if v:  # 跳过空值
                cookies[k] = v
    return cookies



def fetch_html(session: requests.Session, url: str, timeout: int = 15) -> Optional[str]:
    try:
        resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"fetch_html error for {url}: {e}")
        return None


def decode_biz_value(value: str) -> str:
    if not value:
        return value
    if re.fullmatch(r"[A-Za-z0-9+/=]{8,}", value) and len(value) % 4 == 0:
        try:
            decoded = base64.b64decode(value).decode("utf-8")
            if decoded and all(32 <= ord(ch) < 127 for ch in decoded):
                return decoded
        except Exception:
            pass
    return value


def extract_biz_from_article_html(html: str) -> Optional[str]:
    # 常见位置：页面源码中有 __biz="..." 或 profile_ext?action=home&__biz=...
    m = re.search(r"__biz=([\w%\-]+)", html)
    if m:
        return m.group(1)
    m = re.search(r"__biz\"\s*:\s*\"([\w%\-]+)\"", html)
    if m:
        return m.group(1)
    # 公众号页面中也会出现 biz 变量，可能是 base64 编码后再赋值
    m = re.search(r"var\s+biz\s*=\s*\"([A-Za-z0-9+/=]+)\"(?:\s*\|\|\s*\"\")?", html)
    if m:
        return decode_biz_value(m.group(1))
    m = re.search(r"biz\s*:\s*\"([A-Za-z0-9+/=]+)\"", html)
    if m:
        return decode_biz_value(m.group(1))
    m = re.search(r"biz\s*=\s*window\.atob\(\"([A-Za-z0-9+/=]+)\"\)", html)
    if m:
        return decode_biz_value(m.group(1))
    # 查找 mp/profile_ext 的链接
    m = re.search(r"/mp/profile_ext\?action=home&__biz=([\w%\-]+)", html)
    if m:
        return m.group(1)
    return None


def extract_publisher_name_from_article_html(html: str) -> Optional[str]:
    """从文章 HTML 中提取发布者显示名（回退方案，当主页受限时用于搜狗检索）。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        # 常见 id：js_name, js_author_name_text；或 class 包含 rich_media_meta_nickname
        el = soup.find(id="js_name") or soup.find(id="js_author_name_text")
        if el:
            name = el.get_text(strip=True)
            if name:
                return name
        el2 = soup.find(class_=lambda x: x and "rich_media_meta_nickname" in x)
        if el2:
            name = el2.get_text(strip=True)
            if name:
                return name
    except Exception:
        pass
    return None


def parse_msglist_from_home_html(html: str) -> List[str]:
    """尝试从公众号主页 HTML 中解析文章链接列表（尽可能多的策略）。"""
    urls: List[str] = []
    # 1) 查找 var msgList = {...}
    m = re.search(r"var\s+msgList\s*=\s*(\{[\s\S]*?\})\s*;", html)
    if m:
        try:
            obj = json.loads(m.group(1))
            # 结构中通常有 list 或 app_msg_list
            for item in obj.get("list", []):
                content_url = item.get("app_msg_url") or item.get("link") or item.get("content_url")
                if content_url:
                    urls.append(urljoin("https://mp.weixin.qq.com", content_url))
            return urls
        except Exception:
            pass
    # 2) 查找 JSON 字符串被转义的情况，例如: var msgList = JSON.parse('...')
    m = re.search(r"var\s+msgList\s*=\s*JSON.parse\('(.*)'\)\s*;", html)
    if m:
        try:
            s = m.group(1).encode("utf-8").decode("unicode_escape")
            obj = json.loads(s)
            for item in obj.get("list", []):
                content_url = item.get("app_msg_url") or item.get("link") or item.get("content_url")
                if content_url:
                    urls.append(urljoin("https://mp.weixin.qq.com", content_url))
            return urls
        except Exception:
            pass
    # 3) 查找 app_msg_list JSON 片段
    m = re.search(r"app_msg_list\"\s*:\s*(\[.*?\])\s*,\s*\"app_msg_cnt\"", html, flags=re.S)
    if m:
        try:
            arr = json.loads(m.group(1))
            for it in arr:
                link = it.get("link") or it.get("content_url")
                if link:
                    urls.append(urljoin("https://mp.weixin.qq.com", link))
            return urls
        except Exception:
            pass
    # 4) 尝试使用 BeautifulSoup 提取 mp.weixin 链接
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "mp.weixin.qq.com/s" in href:
            urls.append(href)
    return urls


def fetch_msglist_via_ajax(session: requests.Session, biz: str, referer: str, max_count: int = 500, cookies: Optional[dict] = None) -> List[str]:
    """通过 profile_ext?action=getmsg AJAX 接口分页获取文章列表。若传入 cookies 则附带 uin/key/pass_ticket 参数。"""
    urls: List[str] = []
    offset = 0
    count = 10
    cookies = cookies or {}
    uin = cookies.get("uin", cookies.get("wxuin", ""))
    key = cookies.get("key", cookies.get("data_ticket", ""))
    pass_ticket = cookies.get("pass_ticket", cookies.get("data_ticket", ""))
    while True:
        ajax_url = (
            f"https://mp.weixin.qq.com/mp/profile_ext?action=getmsg&__biz={biz}&offset={offset}&count={count}&f=json"
        )
        if uin:
            ajax_url += f"&uin={uin}"
        if key:
            ajax_url += f"&key={key}"
        if pass_ticket:
            ajax_url += f"&pass_ticket={pass_ticket}"
        ajax_url += "&wxtoken=777"
        try:
            resp = session.get(ajax_url, headers={**HEADERS, "Referer": referer, "X-Requested-With": "XMLHttpRequest"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"AJAX getmsg failed at offset {offset}: {e}")
            break
        # 成功时 data 里通常包含 app_msg_list 或 general_msg_list
        app_msg_list = []
        try:
            # data可能嵌套在 'general_msg_list' 中文本为 json 字符串
            if "app_msg_list" in data:
                app_msg_list = data.get("app_msg_list", [])
            elif data.get("general_msg_list"):
                # general_msg_list 是一个 JSON 字符串
                gen = json.loads(data.get("general_msg_list"))
                # gen 中包含 list 字段
                for entry in gen.get("list", []):
                    if entry.get("app_msg_ext_info"):
                        app_msg_list.append(entry["app_msg_ext_info"])
        except Exception:
            pass
        if not app_msg_list:
            break
        new_found = 0
        for it in app_msg_list:
            link = it.get("link") or it.get("content_url")
            if link and "mp.weixin.qq.com/s" in link:
                full = urljoin("https://mp.weixin.qq.com", link)
                if full not in urls:
                    urls.append(full)
                    new_found += 1
        print(f"ajax offset {offset}: found {len(app_msg_list)} items, {new_found} new")
        if new_found == 0:
            break
        offset += count
        if offset >= max_count:
            break
        time.sleep(random.uniform(0.5, 1.5))
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="从单篇文章 URL 抽取公众号文章历史列表")
    parser.add_argument("--url", required=True, help="文章 URL（mp.weixin.qq.com/s?...）或任意页面包含 __biz 的 URL")
    parser.add_argument("--render", action="store_true", help="使用浏览器渲染（Playwright）获取页面，遇到客户端限制时可用")
    parser.add_argument("--cookies", default="", help="Cookie 文件路径 或 分号分隔的 cookie 字符串 (k1=v1; k2=v2)")
    parser.add_argument("--cookies-env", default="", help="从 .env 文件中读取 cookie（通过环境变量名或直读文件）")
    parser.add_argument("--output", default="data/raw/urls_from_article.txt", help="输出 URL 列表文件路径")
    parser.add_argument("--max-pages", type=int, default=200, help="AJAX 最大抓取条数限制")
    args = parser.parse_args()

    # 解析 cookies
    cookie_dict: dict = {}
    if args.cookies:
        cookie_dict = parse_cookies(args.cookies)
    if args.cookies_env:
        env_file = args.cookies_env
        if Path(env_file).exists():
            cookie_dict.update(parse_cookies(env_file))
        else:
            import os as _os
            raw = _os.getenv(args.cookies_env, "")
            if raw:
                cookie_dict.update(parse_cookies(raw))
    if cookie_dict:
        print(f"已加载 {len(cookie_dict)} 个 cookie 字段: {list(cookie_dict.keys())}")

    url = args.url
    out = Path(args.output)
    session = requests.Session()

    # 注入 cookies 到会话
    for k, v in cookie_dict.items():
        session.cookies.set(k, v, domain=".mp.weixin.qq.com")

    biz = extract_biz_from_url(url)
    html = None
    if not biz:
        print("__biz 未在 URL 中找到，尝试抓取文章页面并解析 HTML 来寻找 __biz")
        # 优先使用 requests 抓取；当用户指定 --render 或 requests 返回受限页面时可用 Playwright 回退
        html = fetch_html(session, url)
        if html:
            biz = extract_biz_from_article_html(html)
        if not biz and args.render:
            print("尝试使用 Playwright 渲染文章页面以提取 __biz ...")
            rendered = fetch_html_playwright(url)
            if rendered:
                html = rendered
                biz = extract_biz_from_article_html(html)
    else:
        print(f"从 URL 中解析到 __biz={biz}")

    if not biz:
        print("无法解析到 __biz，结束。请确认 URL 为 mp.weixin.qq.com 的文章链接，或提供文章 HTML 并确保合规")
        return 2

    profile_home = f"https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz={biz}"
    print(f"尝试访问公众号主页: {profile_home}")
    home_html = fetch_html(session, profile_home)
    # 若检测到受限提示且用户同意使用渲染或自动回退，尝试用 Playwright 抓取完整主页
    if home_html and ("请在微信客户端打开链接" in home_html or "你暂无权限查看此页面内容" in home_html):
        print("检测到公众号主页受限为仅微信客户端访问。")
        if args.render:
            print("使用 Playwright 渲染公众号主页以尝试获取完整内容...")
            rendered_home = fetch_html_playwright(profile_home)
            if rendered_home:
                home_html = rendered_home
    # 检测受限/仅微信客户端访问提示
    if home_html and ("请在微信客户端打开链接" in home_html or "你暂无权限查看此页面内容" in home_html):
        print("注意：公众号主页被限制为仅在微信客户端可见（或需要登录/权限）。")
        print("提示：可选方案 - 1) 在浏览器中打开一条文章并导出 cookies，传入会话；2) 使用浏览器渲染抓取（Playwright/Selenium）以获得完整页面；3) 使用搜狗回退检索（脚本会尝试）。")
    urls: List[str] = []
    if home_html:
        urls = parse_msglist_from_home_html(home_html)
    # 若未解析到或数量较少，尝试 AJAX 接口
    if not urls or len(urls) < 5:
        print("主页解析文章较少或失败，尝试 AJAX 接口分页获取文章列表")
        ajax_urls = fetch_msglist_via_ajax(session, biz, profile_home, max_count=args.max_pages, cookies=cookie_dict)
        # 合并去重
        for u in ajax_urls:
            if u not in urls:
                urls.append(u)

    # 回退方案：若主页与 AJAX 均失败，使用 Playwright + 搜狗检索
    if not urls:
        print("主页与 AJAX 均未返回结果，尝试从文章 HTML 提取发布者名并使用 Playwright 搜狗检索作为回退")
        article_html = html or fetch_html(session, url)
        pub_name = None
        if article_html:
            pub_name = extract_publisher_name_from_article_html(article_html)
        if pub_name:
            print(f"检测到发布者名：{pub_name}，调用 Playwright 搜狗检索回退抓取...")
            try:
                # Try importing the Sogou crawler
                sogou_crawl = None
                sogou_path = Path(__file__).resolve().parent / "sogou_wechat_crawler.py"
                try:
                    from scripts.data.sogou_wechat_crawler import crawl_sogou_wechat  # type: ignore
                    sogou_crawl = crawl_sogou_wechat
                except ImportError:
                    if sogou_path.exists():
                        import importlib.util
                        spec = importlib.util.spec_from_file_location("sogou_crawler", str(sogou_path))
                        if spec and spec.loader:
                            mod = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(mod)
                            sogou_crawl = mod.crawl_sogou_wechat
                
                if sogou_crawl:
                    found = sogou_crawl(pub_name, max_articles=50, max_pages=5)
                    for a in found:
                        u = a.get("url", "")
                        if u and u not in urls:
                            urls.append(u)
                    print(f"Sogou 回退发现 {len(found)} 条，合并后总计 {len(urls)} 条")
                else:
                    print("警告：无法加载 Sogou 爬虫模块")
            except Exception as e:
                print(f"Sogou 回退失败: {e}")
        else:
            print("未能从文章 HTML 中提取发布者名，回退检索不可用")

    if not urls:
        print("未能抓到任何文章 URL，可能被平台反爬或该公众号限制历史访问")
        return 3

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fw:
        for u in urls:
            fw.write(u + "\n")
    print(f"wrote {len(urls)} urls to {out}")
    print("提示：如遇反爬可尝试手动获取一条文章的 cookies 或在合规允许下使用浏览器渲染抓取方案（Selenium/Playwright）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
