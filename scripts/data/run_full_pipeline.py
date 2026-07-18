#!/usr/bin/env python3
"""
Run the full data collection pipeline end-to-end.

用法示例：
  python scripts/data/run_full_pipeline.py --mode article --source "https://mp.weixin.qq.com/s/.." --output-dir data/run_outputs
  python scripts/data/run_full_pipeline.py --mode sogou   --source "公众号名称"       --output-dir data/run_outputs

流水线步骤：
  1) 抓取文章 URL 列表
     - mode=article: crawl_wechat_from_article.py（含 Playwright + Sogou 回退）
     - mode=sogou:   sogou_wechat_crawler.py（直接 Sogou 检索）
  2) 抓取内容并匿名化 → crawl_public_posts.py
  3) 文本规范化 + 去重   → normalize_and_deduplicate.py
  4) Schema 校验          → validate_schema.py
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path


def run(cmd, **kwargs):
    print("[RUN]", " ".join(str(c) for c in cmd))
    res = subprocess.run(cmd, **kwargs)
    if res.returncode != 0:
        raise SystemExit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="全流程: 抓取 → 匿名化 → 去重 → 校验")
    parser.add_argument("--mode", choices=["article", "sogou"], required=True,
                        help="article: 从一篇文章 URL 出发; sogou: 从公众号名称 Sogou 检索出发")
    parser.add_argument("--source", required=True,
                        help="article 模式：微信文章 URL; sogou 模式：公众号名称")
    parser.add_argument("--output-dir", default="data/run_outputs", help="输出目录")
    parser.add_argument("--collector", default="D", help="采集者标识 (传递给 anonymizer)")
    parser.add_argument("--max-articles", type=int, default=50, help="Sogou 模式最大文章数")
    parser.add_argument("--terms-checked-at", default=None, help="合规条款检查日期 (YYYY-MM-DD)")
    parser.add_argument("--render", action="store_true",
                        help="article 模式下传给爬虫 --render（使用 Playwright 渲染）")
    parser.add_argument("--cookies", default="", help="article 模式下传给爬虫的 cookie 文件路径或字符串")
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    ts = int(time.time())
    tmp = outdir / f"tmp_{ts}"
    tmp.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    python = sys.executable

    # ── Step 1: 抓取文章 URL 列表 ──
    urls_file = tmp / "urls.txt"
    if args.mode == "article":
        cmd = [
            python, "scripts/data/crawl_wechat_from_article.py",
            "--url", args.source,
            "--output", str(urls_file),
        ]
        if args.render:
            cmd.append("--render")
        if args.cookies:
            cmd.extend(["--cookies", args.cookies])
    else:  # sogou
        cmd = [
            python, "scripts/data/sogou_wechat_crawler.py",
            "--account", args.source,
            "--max-articles", str(args.max_articles),
            "--output", str(urls_file),
        ]
    run(cmd)

    # ── Step 2: 抓取内容 + 匿名化 ──
    anonymized = outdir / "anonymized_posts.jsonl"
    cmd = [
        python, "scripts/data/crawl_public_posts.py",
        "--input", str(urls_file),
        "--output", str(anonymized),
        "--collector", args.collector,
    ]
    if args.terms_checked_at:
        cmd.extend(["--terms-checked-at", args.terms_checked_at])
    run(cmd)

    # ── Step 3: 规范化 + 去重 ──
    deduped = outdir / "anonymized_posts_dedup.jsonl"
    cmd = [
        python, "scripts/data/normalize_and_deduplicate.py",
        str(anonymized), str(deduped),
    ]
    run(cmd)

    # ── Step 4: Schema 校验 ──
    cmd = [
        python, "scripts/data/validate_schema.py",
        str(deduped),
    ]
    run(cmd)

    print("\n✅ 流水线完成。")
    print(f"  URL 列表:     {urls_file}")
    print(f"  匿名化数据:   {anonymized}")
    print(f"  去重后数据:   {deduped}")
    print(f"  临时文件:     {tmp}")


if __name__ == "__main__":
    main()
