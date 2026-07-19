#!/usr/bin/env python3
"""
Run the full data collection pipeline end-to-end.

用法示例：
  # 单公众号
  python scripts/data/run_full_pipeline.py --mode sogou --source "公众号名称" --output-dir data/run_outputs
  # 从文章 URL 出发
  python scripts/data/run_full_pipeline.py --mode article --source "https://mp.weixin.qq.com/s/.." --output-dir data/run_outputs
  # 批量公众号：从 txt 文件按行读取作者名，依次搜索
  python scripts/data/run_full_pipeline.py --mode sogou --accounts-file data/accounts.txt --output-dir data/run_outputs

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


def load_accounts_from_file(filepath: str) -> list:
    """从文本文件按行读取作者名，跳过空行和注释行（# 开头）。"""
    accounts = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                accounts.append(line)
    return accounts


def merge_url_files(tmp_dir: Path, url_files: list, output: Path) -> None:
    """合并多个 URL 文件，按 URL 去重（保留首次出现的标题和发布者）。"""
    seen_urls = set()
    with output.open("w", encoding="utf-8") as out:
        for uf in url_files:
            if not uf.exists():
                continue
            with uf.open("r", encoding="utf-8") as inf:
                for line in inf:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    url = parts[0].strip() if len(parts) >= 1 else ""
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        out.write(line + "\n")


def main():
    parser = argparse.ArgumentParser(description="全流程: 抓取 → 匿名化 → 去重 → 校验")
    parser.add_argument("--mode", choices=["article", "sogou"], required=True,
                        help="article: 从一篇文章 URL 出发; sogou: 从公众号名称 Sogou 检索出发")
    parser.add_argument("--source", default=None,
                        help="article 模式：微信文章 URL; sogou 模式：公众号名称（与 --accounts-file 二选一）")
    parser.add_argument("--accounts-file", default=None,
                        help="批量模式：txt 文件路径，每行一个公众号名称（仅 sogou 模式支持）")
    parser.add_argument("--output-dir", default="data/run_outputs", help="输出目录")
    parser.add_argument("--collector", default="D", help="采集者标识 (传递给 anonymizer)")
    parser.add_argument("--max-articles", type=int, default=50, help="Sogou 模式每个公众号最大文章数")
    parser.add_argument("--terms-checked-at", default=None, help="合规条款检查日期 (YYYY-MM-DD)")
    parser.add_argument("--render", action="store_true",
                        help="article 模式下传给爬虫 --render（使用 Playwright 渲染）")
    parser.add_argument("--cookies", default="", help="article 模式下传给爬虫的 cookie 文件路径或字符串")
    args = parser.parse_args()

    # 校验参数
    if not args.source and not args.accounts_file:
        parser.error("必须提供 --source 或 --accounts-file")
    if args.accounts_file and args.mode != "sogou":
        parser.error("--accounts-file 仅支持 --mode sogou")

    outdir = Path(args.output_dir)
    ts = int(time.time())
    tmp = outdir / f"tmp_{ts}"
    tmp.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    python = sys.executable

    # ── Step 1: 抓取文章 URL 列表 ──
    urls_file = tmp / "urls.txt"

    if args.accounts_file:
        # ─── 批量模式：依次搜索每个公众号 ───
        accounts = load_accounts_from_file(args.accounts_file)
        if not accounts:
            raise SystemExit(f"错误：{args.accounts_file} 中没有找到任何公众号名称")
        print(f"📋 从 {args.accounts_file} 加载了 {len(accounts)} 个公众号: {', '.join(accounts[:5])}{'...' if len(accounts) > 5 else ''}")

        per_account_url_files = []
        for i, account in enumerate(accounts, 1):
            print(f"\n{'='*60}")
            print(f"[{i}/{len(accounts)}] 搜索: {account}")
            print(f"{'='*60}")
            account_url_file = tmp / f"urls_{i:04d}.txt"
            cmd = [
                python, "scripts/data/sogou_wechat_crawler.py",
                "--account", account,
                "--max-articles", str(args.max_articles),
                "--output", str(account_url_file),
            ]
            try:
                run(cmd)
                per_account_url_files.append(account_url_file)
            except SystemExit as e:
                print(f"  ⚠️  公众号 '{account}' 搜索失败 (exit={e.code})，跳过继续...", file=sys.stderr)
            time.sleep(2)  # 礼貌间隔，降低反爬风险

        # 合并所有 URL，去重
        merge_url_files(tmp, per_account_url_files, urls_file)
        total_lines = sum(1 for _ in urls_file.open("r", encoding="utf-8")) if urls_file.exists() else 0
        print(f"\n📦 合并完成：共 {total_lines} 篇文章（去重后）→ {urls_file}")

    elif args.mode == "article":
        cmd = [
            python, "scripts/data/crawl_wechat_from_article.py",
            "--url", args.source,
            "--output", str(urls_file),
        ]
        if args.render:
            cmd.append("--render")
        if args.cookies:
            cmd.extend(["--cookies", args.cookies])
        run(cmd)

    else:  # sogou 单公众号
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
