#!/usr/bin/env python3
"""
爬虫全自动流水线：搜索 URL → 抓取内容 + 图片 + 匿名化。

用法示例：
  # 单公众号
  python scripts/data/run_full_pipeline.py --mode sogou --source "公众号名称" --output-dir data/run_outputs
  # 从文章 URL 出发
  python scripts/data/run_full_pipeline.py --mode article --source "https://mp.weixin.qq.com/s/.." --output-dir data/run_outputs
  # 批量公众号：从 txt 文件按行读取作者名，依次搜索
  python scripts/data/run_full_pipeline.py --mode sogou --accounts-file data/accounts.txt --output-dir data/run_outputs

流水线步骤（仅爬虫，清洗/去重/校验后续单独执行）：
  1) 抓取文章 URL 列表
     - mode=article: crawl_wechat_from_article.py（含 Playwright + Sogou 回退）
     - mode=sogou:   sogou_wechat_crawler.py（直接 Sogou 检索）
  2) 抓取内容并匿名化 → crawl_public_posts.py
     批量模式下每个公众号单独抓取，per-account URL 文件同时作为 --history-urls，
     确保 blogger_history_refs 只包含同博主文章。
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock


def run(cmd, **kwargs):
    print("[RUN]", " ".join(str(c) for c in cmd))
    res = subprocess.run(cmd, **kwargs)
    if res.returncode != 0:
        raise SystemExit(res.returncode)


def load_accounts_from_file(filepath: str) -> list:
    """从文本文件按行读取作者名, 跳过空行和注释行(# 开头)."""
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


def _build_crawl_cmd(python: str, account_url_file: Path, account_output: Path, args) -> list:
    """构建单个公众号的抓取命令。"""
    cmd = [
        python, "scripts/data/crawl_public_posts.py",
        "--input", str(account_url_file),
        "--output", str(account_output),
        "--history-urls", str(account_url_file),
        "--media-dir", str(args.media_dir),
        "--collector", args.collector,
    ]
    if args.no_images:
        cmd.append("--no-images")
    if args.use_llm:
        cmd.append("--use-llm")
    if args.terms_checked_at:
        cmd.extend(["--terms-checked-at", args.terms_checked_at])
    return cmd


def _crawl_one(cmd: list, label: str, print_lock: Lock) -> tuple:
    """执行单个抓取子进程，返回 (success: bool, label: str, message: str)。"""
    with print_lock:
        print(f"\n[启动] {label}")
    try:
        subprocess.run(cmd, check=True)
        return (True, label, "")
    except subprocess.CalledProcessError as e:
        return (False, label, f"exit={e.returncode}")


def batch_crawl_per_account(
    per_account_url_files: list,
    tmp: Path,
    outdir: Path,
    python: str,
    args,
    resume: bool = False,
) -> None:
    """并发批量抓取：每个 per-account URL 文件单独调用 crawl_public_posts.py，
    使用自己的 URL 文件作为 --history-urls（博主历史上下文）。
    每完成一个公众号立即追加写入最终 JSONL，崩溃不丢已完成的记录。

    resume=True 时：读取已有 JSONL 跳过已抓 URL，不清空输出文件，仅增量追加。"""
    workers = getattr(args, "workers", 3)
    workers = max(1, min(workers, len(per_account_url_files)))
    print_lock = Lock()
    write_lock = Lock()

    anonymized = outdir / "anonymized_posts.jsonl"
    is_resume = resume

    # ── 续传模式：加载已抓取 URL，过滤 ──
    crawled_urls: set = set()
    if is_resume and anonymized.exists():
        crawled_urls = _load_crawled_urls(anonymized)
        if crawled_urls:
            print(f"🔁 续传模式：检测到 {len(crawled_urls)} 条已抓取记录，将跳过这些 URL")
    else:
        # 全新抓取：清理上次残留的临时过滤文件
        for f in tmp.glob("*.filtered.txt"):
            try:
                f.unlink()
            except Exception:
                pass

    # 预扫描：构建任务列表（续传时过滤已抓 URL）
    tasks = []
    total_skipped = 0
    filtered_files = []  # 临时过滤文件，用完清理

    for i, account_url_file in enumerate(per_account_url_files):
        if not account_url_file.exists():
            print(f"  ⚠️  {account_url_file.name} 不存在，跳过")
            continue

        input_file = account_url_file
        url_count = sum(1 for _ in account_url_file.open("r", encoding="utf-8") if _.strip())

        if is_resume and crawled_urls:
            filtered, skipped, total = _filter_url_file(account_url_file, crawled_urls)
            total_skipped += skipped
            if filtered is None:
                print(f"  ⏭  {account_url_file.name}: {total} 条全部已抓，跳过")
                continue
            input_file = filtered
            filtered_files.append(filtered)
            url_count = total - skipped
            if skipped > 0:
                print(f"  🔁 {account_url_file.name}: {skipped}/{total} 已抓，剩余 {url_count} 条")

        if url_count == 0:
            print(f"  ⚠️  {account_url_file.name} 无 URL，跳过")
            continue

        account_output = tmp / f"anonymized_{i+1:04d}.jsonl"
        label = f"[{i+1}/{len(per_account_url_files)}] {account_url_file.name} → {account_output.name} ({url_count} URLs)"
        tasks.append((i, label, input_file, account_output))

    if total_skipped > 0:
        print(f"🔁 续传跳过合计: {total_skipped} 条已抓 URL")

    if not tasks:
        print("无有效抓取任务（所有 URL 已抓取完毕）")
        return

    print(f"\n🚀 {'续传' if is_resume else '并发'}抓取: {len(tasks)} 个公众号, {workers} 个并行 worker")

    # 非续传模式清空输出文件；续传模式保留已有内容
    if not is_resume:
        anonymized.write_text("", encoding="utf-8")

    # 并发执行
    succeeded = 0
    results = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {}
        for idx, label, url_file, output_file in tasks:
            cmd = _build_crawl_cmd(python, url_file, output_file, args)
            future = executor.submit(_crawl_one, cmd, label, print_lock)
            future_map[future] = (idx, label, output_file)

        for future in as_completed(future_map):
            idx, label, output_file = future_map[future]
            try:
                ok, _, err_msg = future.result()
                if ok:
                    with print_lock:
                        print(f"  ✓ 完成 {label}")
                    _append_to_final(anonymized, output_file, write_lock)
                    succeeded += 1
                else:
                    with print_lock:
                        print(f"  ✗ 失败 {label}: {err_msg}", file=sys.stderr)
                results[idx] = (ok, output_file)
            except Exception as exc:
                with print_lock:
                    print(f"  ✗ 异常 {idx}: {exc}", file=sys.stderr)
                results[idx] = (False, output_file)

    # 清理临时过滤文件
    for ff in filtered_files:
        try:
            ff.unlink()
        except Exception:
            pass

    total_records = sum(
        1 for _ in anonymized.open("r", encoding="utf-8")
        if _.strip() and not _.strip().startswith("#")
    ) if anonymized.exists() else 0
    print(f"\n📦 完成：{succeeded}/{len(tasks)} 公众号成功, 共 {total_records} 条记录 → {anonymized}")
    print(f"  图片目录:     {args.media_dir}")


def _append_to_final(anonymized: Path, account_output: Path, write_lock: Lock) -> None:
    """将单个公众号的抓取结果追加到最终 JSONL 文件（线程安全，按完成顺序写入）。"""
    if not account_output.exists():
        return
    text = account_output.read_text(encoding="utf-8").strip()
    if not text:
        return
    with write_lock:
        # 如果文件中已有内容，加空行分隔
        need_sep = anonymized.exists() and anonymized.stat().st_size > 0
        with anonymized.open("a", encoding="utf-8") as out:
            if need_sep:
                out.write("\n")
            out.write(text)
            out.write("\n")


def _load_crawled_urls(jsonl_path: Path) -> set:
    """从已有 JSONL 中提取已抓取的 source_url 集合。"""
    crawled = set()
    if not jsonl_path.exists():
        return crawled
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("{"):
                    # 跳过空行/注释行，尝试解析 JSON
                    pass
        # 重新用 JSON 逐记录解析（处理缩进 JSONL）
        content = jsonl_path.read_text(encoding="utf-8")
        import re as _re
        # 匹配顶层 JSON 对象
        for m in _re.finditer(r'"source_url"\s*:\s*"([^"]+)"', content):
            crawled.add(m.group(1))
    except Exception:
        pass
    return crawled


def _filter_url_file(url_file: Path, crawled_urls: set) -> tuple:
    """从 URL 文件中剔除已抓取的 URL，返回 (filtered_path, skipped_count, total_count)。
    如果全部已抓取，返回 (None, total, total)。"""
    lines = []
    skipped = 0
    total = 0
    with url_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            # URL 是 tab 分隔的第一个字段
            url = line.split("\t")[0].strip()
            if url in crawled_urls:
                skipped += 1
                continue
            lines.append(line)

    if not lines:
        return (None, skipped, total)

    # 写入临时过滤文件（如果输入已是 filtered，覆盖而非叠加后缀）
    if ".filtered" in url_file.name:
        filtered_path = url_file
    else:
        filtered_path = url_file.with_suffix(".filtered.txt")
    filtered_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return (filtered_path, skipped, total)


def main():
    parser = argparse.ArgumentParser(description="全流程: 抓取 → 匿名化 → 去重 → 校验")
    parser.add_argument("--mode", choices=["article", "sogou"], required=True,
                        help="article: 从一篇文章 URL 出发; sogou: 从公众号名称 Sogou 检索出发")
    parser.add_argument("--source", default=None,
                        help="article 模式：微信文章 URL; sogou 模式：公众号名称（与 --accounts-file 二选一）")
    parser.add_argument("--accounts-file", default=None,
                        help="批量模式：txt 文件路径，每行一个公众号名称（仅 sogou 模式支持）")
    parser.add_argument("--output-dir", default="data/run_outputs", help="输出目录")
    parser.add_argument("--media-dir", default="data/media", help="图片下载目录")
    parser.add_argument("--no-images", action="store_true", help="跳过图片下载（快速模式）")
    parser.add_argument("--use-llm", action="store_true", help="使用 LLM 从原始 HTML 提取纯净正文 + 图片标注")
    parser.add_argument("--collector", default="D", help="采集者标识 (传递给 anonymizer)")
    parser.add_argument("--max-articles", type=int, default=50, help="Sogou 模式每个公众号最大文章数")
    parser.add_argument("--terms-checked-at", default=None, help="合规条款检查日期 (YYYY-MM-DD)")
    parser.add_argument("--render", action="store_true",
                        help="article 模式下传给爬虫 --render（使用 Playwright 渲染）")
    parser.add_argument("--cookies", default="", help="article 模式下传给爬虫的 cookie 文件路径或字符串")
    parser.add_argument("--resume", action="store_true",
                        help="断点续传：自动检测 output-dir 下最新 tmp 目录，若已有 URL 文件则跳过搜索直接抓取")
    parser.add_argument("--resume-from", default=None,
                        help="断点续传：指定 tmp 目录路径，跳过搜索从该目录的 URL 文件直接抓取")
    parser.add_argument("--workers", type=int, default=3,
                        help="批量模式并发 worker 数（默认 3，每个 worker 处理一个公众号）")
    args = parser.parse_args()

    # 校验参数
    if not args.source and not args.accounts_file and not args.resume and not args.resume_from:
        parser.error("必须提供 --source、--accounts-file、--resume 或 --resume-from 之一")
    if args.accounts_file and args.mode != "sogou":
        parser.error("--accounts-file 仅支持 --mode sogou")

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    # ── 断点续传：检测已有 tmp 目录 ──
    urls_file = None
    tmp = None
    per_account_url_files: list = []  # 批量模式的分文件列表
    is_batch_resume = False

    if args.resume_from:
        tmp = Path(args.resume_from)
        # 优先检测批量分文件 urls_*.txt（排除 .filtered.txt 残留）
        batch_files = sorted(
            f for f in tmp.glob("urls_*.txt") if ".filtered" not in f.name
        )
        if batch_files:
            per_account_url_files = batch_files
            is_batch_resume = True
            total = sum(1 for f in batch_files for _ in f.open("r", encoding="utf-8") if _.strip())
            print(f"断点续传 (指定, 批量): 从 {tmp} 恢复, {len(batch_files)} 个分文件, 共 {total} 个 URL, 跳过搜索")
        else:
            candidate = tmp / "urls.txt"
            if candidate.exists():
                urls_file = candidate
                total = sum(1 for _ in candidate.open("r", encoding="utf-8") if _.strip())
                print(f"断点续传 (指定): 从 {tmp} 恢复, 已有 {total} 个 URL, 跳过搜索")
            else:
                print(f"{tmp} 中未找到 urls_*.txt 或 urls.txt, 回退到正常流程")
                tmp = None

    elif args.resume:
        if outdir.exists():
            tmp_dirs = sorted(
                [d for d in outdir.iterdir() if d.is_dir() and d.name.startswith("tmp_")],
                key=lambda d: d.stat().st_mtime, reverse=True)
            for td in tmp_dirs:
                # 优先检测批量分文件（排除 .filtered.txt 残留）
                batch_files = sorted(
                    f for f in td.glob("urls_*.txt") if ".filtered" not in f.name
                )
                if batch_files:
                    tmp = td
                    per_account_url_files = batch_files
                    is_batch_resume = True
                    total = sum(1 for f in batch_files for _ in f.open("r", encoding="utf-8") if _.strip())
                    print(f"断点续传 (自动, 批量): 检测到 {td.name}, {len(batch_files)} 个分文件, 共 {total} 个 URL, 跳过搜索")
                    break
                candidate = td / "urls.txt"
                if candidate.exists():
                    tmp = td
                    urls_file = candidate
                    total = sum(1 for _ in candidate.open("r", encoding="utf-8") if _.strip())
                    print(f"断点续传 (自动): 检测到 {td.name}, 已有 {total} 个 URL, 跳过搜索")
                    break
            if not tmp:
                print("未检测到可恢复的 tmp 目录, 回退到正常流程")
        else:
            print("output-dir 不存在, 回退到正常流程")

    if tmp is None:
        ts = int(time.time())
        tmp = outdir / f"tmp_{ts}"
        tmp.mkdir(parents=True, exist_ok=True)
        urls_file = tmp / "urls.txt"

    # ── 批量断点续传：跳过搜索，直接用已有分文件抓取 ──
    if is_batch_resume and per_account_url_files:
        print(f"\n Step 1 跳过（批量续传: {len(per_account_url_files)} 个分文件已就绪）")
        batch_crawl_per_account(per_account_url_files, tmp, outdir, python, args, resume=True)
        return

    # ── Step 1: 抓取文章 URL 列表（断点续传时跳过）──
    skip_step1 = urls_file.exists() and \
        sum(1 for _ in urls_file.open("r", encoding="utf-8") if _.strip()) > 0

    if skip_step1:
        print(f"\n Step 1 跳过（URL 文件已存在: {urls_file}）")
    elif args.accounts_file:
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

        # ─── Step 2 (批量): 每个公众号单独抓取，用自己的 URL 文件做历史上下文 ───
        batch_crawl_per_account(per_account_url_files, tmp, outdir, python, args, resume=False)
        return  # 批量模式到此结束，不走下面的单次抓取逻辑

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

    # ── Step 2: 抓取内容 + 匿名化（传入全部 URL 列表作为博主历史）──
    anonymized = outdir / "anonymized_posts.jsonl"
    cmd = [
        python, "scripts/data/crawl_public_posts.py",
        "--input", str(urls_file),
        "--output", str(anonymized),
        "--history-urls", str(urls_file),     # ← 全部 URL 作为博主历史
        "--media-dir", str(args.media_dir),
        "--collector", args.collector,
    ]
    if args.no_images:
        cmd.append("--no-images")
    if args.use_llm:
        cmd.append("--use-llm")
    if args.terms_checked_at:
        cmd.extend(["--terms-checked-at", args.terms_checked_at])
    run(cmd)

    # ── 完成 ──
    # 清洗（normalize_and_deduplicate.py）和校验（validate_schema.py）后续单独执行

    print("\n✅ 流水线完成。")
    print(f"  URL 列表:     {urls_file}")
    print(f"  匿名化数据:   {anonymized}")
    print(f"  图片目录:     {args.media_dir}")
    print(f"  临时文件:     {tmp}")
    print(f"\n  后续步骤:")
    print(f"    python scripts/data/normalize_and_deduplicate.py {anonymized} {outdir / 'anonymized_posts_dedup.jsonl'}")
    print(f"    python scripts/data/validate_schema.py {outdir / 'anonymized_posts_dedup.jsonl'}")


if __name__ == "__main__":
    main()
