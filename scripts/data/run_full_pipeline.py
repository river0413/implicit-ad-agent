#!/usr/bin/env python3
"""
Run the full data collection pipeline end-to-end.

Usage examples:
python scripts/data/run_full_pipeline.py --mode article --source "https://mp.weixin.qq.com/s/.." --output-dir data/run_outputs
python scripts/data/run_full_pipeline.py --mode account --source "公众号名称" --output-dir data/run_outputs --collector X

This script orchestrates existing scripts in `scripts/data/`:
- crawl_wechat_from_article.py (article -> urls)
- crawl_wechat_account.py (account -> urls)
- crawl_public_posts.py (urls -> anonymized jsonl)
- normalize_and_deduplicate.py (anonymized -> deduped)

It runs subprocesses and writes outputs under `--output-dir`.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path


def run(cmd, **kwargs):
    print("RUN:", " ".join(cmd))
    res = subprocess.run(cmd, **kwargs)
    if res.returncode != 0:
        raise SystemExit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="Run full pipeline: crawl -> anonymize -> dedup")
    parser.add_argument("--mode", choices=["article", "account"], required=True, help="输入类型：article 或 account")
    parser.add_argument("--source", required=True, help="文章 URL（mode=article）或公众号名称（mode=account）")
    parser.add_argument("--output-dir", default="data/run_outputs", help="输出目录")
    parser.add_argument("--collector", default="D", help="collector id passed to anonymizer")
    parser.add_argument("--max-pages", type=int, default=5, help="仅在 account 模式下传给抓取脚本的页数上限")
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    ts = int(time.time())
    tmp = outdir / f"tmp_{ts}"
    tmp.mkdir(parents=True, exist_ok=True)

    python = sys.executable

    # 1) generate URLs
    if args.mode == "article":
        urls_file = tmp / "urls_from_article.txt"
        cmd = [python, "scripts/data/crawl_wechat_from_article.py", "--url", args.source, "--output", str(urls_file)]
    else:
        urls_file = tmp / "urls_from_account.txt"
        cmd = [python, "scripts/data/crawl_wechat_account.py", "--account", args.source, "--max-pages", str(args.max_pages), "--output", str(urls_file)]

    run(cmd)

    # 2) anonymize / fetch content
    anonymized = outdir / "anonymized_posts.jsonl"
    cmd = [python, "scripts/data/crawl_public_posts.py", "--input", str(urls_file), "--output", str(anonymized), "--collector", args.collector]
    run(cmd)

    # 3) normalize and deduplicate
    deduped = outdir / "anonymized_posts_dedup.jsonl"
    cmd = [python, "scripts/data/normalize_and_deduplicate.py", str(anonymized), str(deduped)]
    run(cmd)

    print("Pipeline finished successfully.")
    print(f"URLs: {urls_file}")
    print(f"Anonymized: {anonymized}")
    print(f"Deduplicated: {deduped}")
    print("Temporary files kept at:", tmp)


if __name__ == "__main__":
    raise SystemExit(main())
