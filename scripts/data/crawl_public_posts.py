#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


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


def platform_from_url(url: str) -> str:
    if "mp.weixin.qq.com" in url or "weixin.qq.com" in url:
        return "wechat_official_account"
    if "weibo.com" in url or "m.weibo.cn" in url:
        return "weibo_public_account"
    return "web_public"


def fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="ignore")


def build_post_record(
    url: str,
    publisher_name: str,
    publisher_id: str,
    content: str,
    salt: str,
    collector: str,
    terms_checked_at: Optional[str],
) -> Dict:
    published_at = datetime.utcnow().isoformat() + "+00:00"
    source_ref_hash = stable_hash(url, salt, length=32)
    blogger_id = stable_hash(publisher_id or publisher_name or url, salt, length=24)
    anonymized_name = fuzzy_name(publisher_name)
    post_id = stable_hash(url, salt, length=24)

    return {
        "schema_version": "1.0",
        "post_id": post_id,
        "platform": platform_from_url(url),
        "source_type": "manual_public_collection",
        "blogger_id": blogger_id,
        "blogger_name": anonymized_name,
        "published_at": published_at,
        "text": content,
        "media": [],
        "comments": [],
        "blogger_history_refs": [],
        "provenance": {
            "source_ref_hash": source_ref_hash,
            "collected_at": published_at,
            "collector": collector,
            "terms_checked_at": terms_checked_at,
        },
        "privacy": {
            "anonymized": True,
            "contains_sensitive_data": False,
        },
    }


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
    parser.add_argument("--collector", default="D", help="Collector identifier")
    parser.add_argument("--terms-checked-at", default=None, help="Terms check date (YYYY-MM-DD)")
    args = parser.parse_args()

    salt = get_salt()
    input_path = Path(args.input)
    output_path = Path(args.output)
    urls = load_urls(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for item in urls:
        url = item["url"]
        publisher_name = item["publisher_name"]
        publisher_id = item["publisher_id"]
        try:
            html = fetch_url(url)
            title = extract_title(html)
            text = extract_text(html)
            content = title + "\n" + text if title else text
            record = build_post_record(
                url=url,
                publisher_name=publisher_name,
                publisher_id=publisher_id,
                content=content,
                salt=salt,
                collector=args.collector,
                terms_checked_at=args.terms_checked_at,
            )
            records.append(record)
            print(f"collected {url}")
        except Exception as exc:
            print(f"failed {url}: {exc}", file=sys.stderr)

    with output_path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"wrote {len(records)} anonymized records to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
