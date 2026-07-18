#!/usr/bin/env python3
"""
从公众号名称检索并抓取文章 URL 列表（输出为 URL 列表文件，供 crawl_public_posts.py 使用）。
注意：本脚本尝试使用搜狗微信搜索页面（weixin.sogou.com）检索公开文章链接。
请确保仅对允许采集的公开账号进行抓取，遵守平台使用条款并控制请求速率。
"""
import argparse
import random
import time
from pathlib import Path
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

HEADERS = {"User-Agent": USER_AGENT}


def search_sogou(account_name: str, page: int = 1) -> str:
    q = quote_plus(account_name)
    url = f"https://weixin.sogou.com/weixin?type=1&query={q}&page={page}"
    return url


def fetch_html(session: requests.Session, url: str, timeout: int = 20) -> str:
    resp = session.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def resolve_redirect(session: requests.Session, href: str) -> str:
    """尝试跟随 href 的跳转并返回最终 URL（若发生异常或非 HTTP，返回原始 href）"""
    try:
        if href.startswith("/"):
            href = urljoin("https://weixin.sogou.com", href)
        if not href.startswith("http"):
            return href
        resp = session.get(href, headers=HEADERS, timeout=15, allow_redirects=True)
        return resp.url or href
    except Exception:
        return href


def extract_article_links_from_search(session: requests.Session, html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    # 搜索结果可能包含直接 mp.weixin.qq.com 链接或跳转链接（weixin.sogou.com/link?...）
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "mp.weixin.qq.com/s" in href:
            links.append(href)
            continue
        # 尝试解析跳转并检查最终 URL
        final = resolve_redirect(session, href)
        if "mp.weixin.qq.com/s" in final:
            links.append(final)
    return links


def collect_article_urls(account_name: str, max_pages: int = 5, delay_range=(1, 3)) -> List[str]:
    collected = []
    seen = set()
    session = requests.Session()
    for p in range(1, max_pages + 1):
        url = search_sogou(account_name, page=p)
        try:
            html = fetch_html(session, url)
        except Exception as exc:
            print(f"failed to fetch search page {p}: {exc}")
            break
        links = extract_article_links_from_search(session, html)
        new = 0
        for l in links:
            if l not in seen:
                seen.add(l)
                collected.append(l)
                new += 1
        print(f"page {p}: found {len(links)} links, {new} new")
        if new == 0:
            # 若某页没有新内容，可尝试继续少量页码或退出
            print("no new links on this page, stopping early")
            break
        time.sleep(random.uniform(*delay_range))
    return collected


def write_urls(urls: List[str], output_path: Path, publisher_name: str = "") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fw:
        for u in urls:
            if publisher_name:
                fw.write(f"{u}\t{publisher_name}\n")
            else:
                fw.write(f"{u}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect article URLs by WeChat public account name.")
    parser.add_argument("--account", required=True, help="公众号名称（中文）或其别名")
    parser.add_argument("--max-pages", type=int, default=5, help="最多翻页数，默认 5")
    parser.add_argument("--output", default="data/raw/urls_from_account.txt", help="输出 URL 列表文件")
    parser.add_argument("--publisher-name", default="", help="采集到的发布者显示名（可选），会写入输出文件作为第二列")
    args = parser.parse_args()

    print(f"searching account: {args.account}")
    urls = collect_article_urls(args.account, max_pages=args.max_pages)
    print(f"collected {len(urls)} URLs")
    write_urls(urls, Path(args.output), publisher_name=args.publisher_name)
    print(f"wrote urls to {args.output}")
    print("Next: run crawl_public_posts.py with the output file as input to fetch and anonymize content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
