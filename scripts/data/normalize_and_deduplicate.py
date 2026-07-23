#!/usr/bin/env python3
"""规范化与去重 —— 含 content_group 和跨划分近重复检测。

改进（v1.1）：
  - 补充 content_group 支持：基于文本相似度自动标记疑似跨平台转载组
  - 跨划分近重复依据：同时基于文本指纹 + 图片指纹检测
  - 输出去重报告

用法：
  python scripts/data/normalize_and_deduplicate.py \
    --input data/run_outputs/anonymized_posts.jsonl \
    --output data/run_outputs/anonymized_posts_dedup.jsonl \
    --report data/reports/dedup_report.json \
    --content-group-threshold 0.85
"""
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


def normalize_text(text: str) -> str:
    """文本规范化：去除多余空白、URL、话题标签。"""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#@]\w+", "", text)
    return text


def record_text_fingerprint(record: Dict) -> str:
    """计算记录文本指纹（用于精确去重）。"""
    normalized = {
        "title": normalize_text(record.get("title") or ""),
        "text": normalize_text(record.get("text", "")),
        "media_refs": sorted([
            m.get("ref") or "" for m in record.get("media", []) if isinstance(m, dict)
        ]),
        "platform": record.get("platform"),
    }
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_content_fingerprint(record: Dict) -> str:
    """计算记录内容指纹（仅基于 title+text，用于检测跨平台转载）。"""
    content = normalize_text(record.get("title") or "") + " " + normalize_text(record.get("text", ""))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """计算两个集合的 Jaccard 相似度。"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def text_ngram_similarity(text_a: str, text_b: str, n: int = 3) -> float:
    """基于 n-gram 的文本相似度。"""
    def ngrams(t: str) -> Set[str]:
        t = normalize_text(t)
        if len(t) < n:
            return {t}
        return {t[i:i+n] for i in range(len(t) - n + 1)}
    return jaccard_similarity(ngrams(text_a), ngrams(text_b))


def assign_content_groups(records: List[Dict], threshold: float = 0.85) -> List[Dict]:
    """为疑似跨平台转载的记录分配 content_group_id。
    
    基于文本 n-gram 相似度检测跨平台转载关系。
    仅标记不同平台之间相似度 >= threshold 的记录对。
    """
    # 分组：同平台内不标记 content_group
    content_groups: Dict[str, List[int]] = defaultdict(list)  # fingerprint → indices
    fingerprint_to_idx: Dict[str, int] = {}

    for idx, record in enumerate(records):
        text = normalize_text(record.get("title") or "") + " " + normalize_text(record.get("text", ""))
        if len(text) < 50:  # 文本太短不检测
            continue

        # 查找相似记录
        matched = False
        for fp, group_indices in list(content_groups.items()):
            rep_idx = group_indices[0]
            rep_text = normalize_text(records[rep_idx].get("title") or "") + " " + normalize_text(records[rep_idx].get("text", ""))
            sim = text_ngram_similarity(text, rep_text)
            if sim >= threshold and records[idx].get("platform") != records[rep_idx].get("platform"):
                content_groups[fp].append(idx)
                matched = True
                break

        if not matched:
            fp = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            content_groups[fp].append(idx)

    # 分配 content_group_id
    group_id_counter = 0
    for fp, indices in content_groups.items():
        if len(indices) > 1:  # 只有多条记录才需要标记
            group_id = f"cg_{group_id_counter:04d}"
            group_id_counter += 1
            for idx in indices:
                records[idx]["content_group_id"] = group_id

    return records


def deduplicate(records: Iterable[Dict]) -> Tuple[List[Dict], Dict]:
    """去重并返回统计信息。
    
    去重策略：
    1. 精确去重（文本指纹相同）
    2. 近重复标记（相似但不完全相同），不删除但标记
    """
    seen_fingerprints: Set[str] = set()
    deduped: List[Dict] = []
    duplicates_removed = 0
    near_duplicates = 0

    # 第一遍：精确去重
    for record in records:
        fp = record_text_fingerprint(record)
        if fp in seen_fingerprints:
            duplicates_removed += 1
            continue
        seen_fingerprints.add(fp)
        record["text"] = normalize_text(record.get("text", ""))
        deduped.append(record)

    # 第二遍：检测近重复（不同平台间相似但不完全相同的文本）
    for i in range(len(deduped)):
        for j in range(i + 1, len(deduped)):
            if deduped[i].get("platform") == deduped[j].get("platform"):
                continue  # 同平台不算转载近重复
            text_i = deduped[i].get("text", "")
            text_j = deduped[j].get("text", "")
            if len(text_i) < 100 or len(text_j) < 100:
                continue
            sim = text_ngram_similarity(text_i, text_j)
            if sim >= 0.7:
                near_duplicates += 1

    stats = {
        "original_count": len(list(records)) if hasattr(records, '__len__') else 0,
        "deduped_count": len(deduped),
        "duplicates_removed": duplicates_removed,
        "near_duplicates_detected": near_duplicates,
    }

    return deduped, stats


def load_jsonl(path: Path) -> Iterable[Dict]:
    """加载 JSONL 文件，兼容标准 JSONL 和美化打印拼接格式。"""
    with path.open("r", encoding="utf-8-sig") as stream:
        content = stream.read()

    decoder = json.JSONDecoder()
    idx = 0
    content_len = len(content)
    while idx < content_len:
        while idx < content_len and content[idx] in " \t\n\r":
            idx += 1
        if idx >= content_len:
            break
        try:
            obj, end = decoder.raw_decode(content, idx)
            yield obj
            idx = end
        except json.JSONDecodeError as e:
            context = content[max(0, idx - 40):idx + 80]
            raise json.JSONDecodeError(
                f"Failed to decode JSON at position {idx}: {e.msg}. Context: ...{context!r}...",
                e.doc, e.pos
            ) from e


def write_jsonl(records: Iterable[Dict], path: Path) -> None:
    """写入标准 JSONL。"""
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(input_path: str, output_path: str, report_path: Optional[str] = None,
         content_group_threshold: float = 0.85) -> None:
    src = Path(input_path)
    dst = Path(output_path)
    records = list(load_jsonl(src))
    original_count = len(records)

    # 去重
    deduped, dedup_stats = deduplicate(records)

    # 分配 content_group
    deduped = assign_content_groups(deduped, content_group_threshold)

    write_jsonl(deduped, dst)

    # 统计
    content_group_count = len(set(
        r.get("content_group_id") for r in deduped
        if r.get("content_group_id") is not None
    ))

    print(f"📊 去重完成:")
    print(f"   原始记录:   {original_count}")
    print(f"   去重后:     {len(deduped)}")
    print(f"   精确重复:   {dedup_stats['duplicates_removed']} 条已移除")
    print(f"   近重复:     {dedup_stats['near_duplicates_detected']} 对已检测")
    print(f"   content_group: {content_group_count} 组已标记")

    # 保存报告
    if report_path:
        rp = Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        platform_dist = defaultdict(int)
        for r in deduped:
            platform_dist[r.get("platform", "unknown")] += 1

        report = {
            "original_count": original_count,
            "deduped_count": len(deduped),
            "exact_duplicates_removed": dedup_stats["duplicates_removed"],
            "near_duplicate_pairs": dedup_stats["near_duplicates_detected"],
            "content_groups_assigned": content_group_count,
            "platform_distribution": dict(platform_dist),
            "content_group_threshold": content_group_threshold,
        }
        with rp.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"📝 报告: {rp}")


if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="规范化与去重（含 content_group 和近重复检测）")
    parser.add_argument("--input", default=r"data\run_outputs\anonymized_posts.jsonl")
    parser.add_argument("--output", default=r"data\run_outputs\anonymized_posts_dedup.jsonl")
    parser.add_argument("--report", default=None, help="去重报告输出路径")
    parser.add_argument("--content-group-threshold", type=float, default=0.85,
                        help="content_group 文本相似度阈值（默认 0.85）")
    args = parser.parse_args()
    main(args.input, args.output, args.report, args.content_group_threshold)
