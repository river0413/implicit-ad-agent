#!/usr/bin/env python3
"""
Sogou WeChat article crawler using Playwright.
Search for articles by account name, filter by publisher, resolve redirect links.
"""
import time, re, sys, argparse
from urllib.parse import urljoin, quote
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


def crawl_sogou_wechat(account_name: str, max_articles: int = 50, max_pages: int = 10):
    """Crawl Sogou WeChat search for articles from a specific account.
    
    Parses type=2 search results, filters by <span class="all-time-y2"> publisher name,
    and resolves Sogou's encrypted /link?url= redirects to mp.weixin.qq.com URLs.
    """
    query = quote(account_name)
    results = []
    seen_links = set()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()
        
        for page_num in range(1, max_pages + 1):
            if len(results) >= max_articles:
                break
            
            search_url = f"https://weixin.sogou.com/weixin?type=2&query={query}&page={page_num}"
            print(f"\n[Page {page_num}] Loading...")
            
            try:
                page.goto(search_url, wait_until="networkidle", timeout=30000)
                time.sleep(3)
            except Exception as e:
                print(f"  Failed: {e}")
                break
            
            soup = BeautifulSoup(page.content(), "html.parser")
            
            # Extract entries with publisher info
            entries = []
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "link?url=" not in href:
                    continue
                title = a.get_text(strip=True)
                if not title or len(title) <= 3:
                    continue
                
                link = urljoin("https://weixin.sogou.com", href)
                
                # Find publisher: look for nearest <span class="all-time-y2">
                # It's usually in the parent <div> or <li>
                parent = a.parent
                publisher = ""
                for _ in range(5):  # walk up to 5 levels
                    if parent is None:
                        break
                    pub_span = parent.find("span", class_="all-time-y2")
                    if pub_span:
                        publisher = pub_span.get_text(strip=True)
                        break
                    parent = parent.parent
                
                entries.append({"title": title, "link": link, "publisher": publisher})
            
            # Filter by account name
            matching = [e for e in entries if account_name.lower() in e["publisher"].lower()]
            print(f"  {len(entries)} results, {len(matching)} from '{account_name}'")
            
            if not matching:
                print("  No more matching results, stopping.")
                break
            
            # Resolve redirect links
            for entry in matching:
                if len(results) >= max_articles:
                    break
                if entry["link"] in seen_links:
                    continue
                seen_links.add(entry["link"])
                
                try:
                    new_page = context.new_page()
                    new_page.goto(entry["link"], wait_until="domcontentloaded", timeout=20000)
                    try:
                        new_page.wait_for_url("**mp.weixin.qq.com**", timeout=10000)
                    except:
                        pass
                    time.sleep(1.5)
                    final_url = new_page.url
                    new_page.close()
                    
                    if "mp.weixin.qq.com" in final_url:
                        results.append({"title": entry["title"], "url": final_url, "publisher": entry["publisher"]})
                        print(f"  [{len(results)}] {entry['title'][:50]}")
                    else:
                        print(f"  [skip] no redirect")
                except Exception as e:
                    print(f"  [err] {str(e)[:60]}")
                    try: new_page.close()
                    except: pass
            
            time.sleep(1)
        
        browser.close()
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Sogou WeChat article crawler (Playwright)")
    parser.add_argument("--account", required=True, help="Public account name")
    parser.add_argument("--max-articles", type=int, default=50, help="Max articles to fetch")
    parser.add_argument("--max-pages", type=int, default=10, help="Max search pages")
    parser.add_argument("--output", default="data/run_outputs/urls_from_sogou.txt", help="Output file")
    args = parser.parse_args()
    
    print(f"Searching Sogou for: {args.account}")
    articles = crawl_sogou_wechat(args.account, args.max_articles, args.max_pages)
    
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for a in articles:
            f.write(f"{a['url']}\t{a['title']}\t{a['publisher']}\n")
    
    print(f"\n{'='*60}")
    print(f"Done! {len(articles)} articles saved to {out_path}")
    for a in articles:
        print(f"  {a['title'][:50]}")
        print(f"  -> {a['url'][:100]}")


if __name__ == "__main__":
    main()
