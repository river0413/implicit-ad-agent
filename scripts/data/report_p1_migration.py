#!/usr/bin/env python3
"""P1 迁移报告：输出成功/降级/拒绝记录数和字段缺失分布。

用法：
  python scripts/data/report_p1_migration.py \
    --input data/interim/candidates_v1.jsonl \
    --id-map data/interim/id_mapping_v1.json \
    --output data/reports/migration_report.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

CST = timezone(timedelta(hours=8))


def load_jsonl(path: Path) -> List[Dict]:
    """加载 JSONL 文件。"""
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def generate_report(input_path: Path, id_map_path: Path) -> Dict:
    """生成迁移报告。"""
    records = load_jsonl(input_path)

    # 基础统计
    total = len(records)
    if total == 0:
        return {"error": "No records found", "total": 0}

    # 状态分布
    status_counts = Counter()
    for r in records:
        meta = r.get("_migration_meta", {})
        if meta.get("llm_needs_review"):
            status_counts["degraded"] += 1
        else:
            status_counts["success"] += 1

    # 平台分布
    platform_counts = Counter(r.get("platform", "unknown") for r in records)

    # source_type 分布
    source_counts = Counter(r.get("source_type", "unknown") for r in records)

    # 字段缺失分布
    field_missing: Dict[str, int] = defaultdict(int)
    for r in records:
        for field in ["title", "content_group_id", "published_at"]:
            if r.get(field) is None:
                field_missing[field] += 1
        if not r.get("comments"):
            field_missing["comments"] += 1
        if not r.get("blogger_history_refs"):
            field_missing["blogger_history_refs"] += 1

    # media 字段缺失
    media_total = 0
    media_sha256_missing = 0
    media_phash_missing = 0
    media_ocr_missing = 0
    for r in records:
        for m in r.get("media", []):
            media_total += 1
            if m.get("sha256") is None:
                media_sha256_missing += 1
            if m.get("phash") is None:
                media_phash_missing += 1
            if m.get("ocr_text") is None:
                media_ocr_missing += 1

    # provenance 核验状态
    terms_checked = sum(
        1 for r in records
        if r.get("provenance", {}).get("terms_checked_at") is not None
    )
    terms_unchecked = total - terms_checked

    # llm_needs_review 统计
    llm_review_count = sum(
        1 for r in records
        if r.get("_migration_meta", {}).get("llm_needs_review", False)
    )

    # 文本长度分布
    text_lengths = [len(r.get("text", "")) for r in records]
    media_counts_per_post = [len(r.get("media", [])) for r in records]

    report = {
        "report_generated_at": datetime.now(CST).isoformat(),
        "summary": {
            "total_records": total,
            "success": status_counts.get("success", 0),
            "degraded": status_counts.get("degraded", 0),
            "degraded_reason": "llm_needs_review=true — LLM 抽取置信度不能当标签置信度",
        },
        "platform_distribution": dict(platform_counts.most_common()),
        "source_type_distribution": dict(source_counts.most_common()),
        "field_completeness": {
            field: {
                "missing": count,
                "missing_pct": round(count / total * 100, 1),
                "present": total - count,
                "present_pct": round((total - count) / total * 100, 1),
            }
            for field, count in sorted(field_missing.items())
        },
        "media_quality": {
            "total_media_items": media_total,
            "sha256_missing": media_sha256_missing,
            "sha256_missing_pct": round(media_sha256_missing / max(media_total, 1) * 100, 1),
            "phash_missing": media_phash_missing,
            "phash_missing_pct": round(media_phash_missing / max(media_total, 1) * 100, 1),
            "ocr_text_missing": media_ocr_missing,
            "ocr_text_missing_pct": round(media_ocr_missing / max(media_total, 1) * 100, 1),
        },
        "provenance_audit": {
            "terms_checked": terms_checked,
            "terms_unchecked": terms_unchecked,
            "warning": "terms_checked_at 为空的记录不得进入可公开金标" if terms_unchecked > 0 else None,
        },
        "llm_review_queue": {
            "needs_review_count": llm_review_count,
            "action_required": "建立复核队列，不要把 LLM 抽取置信度当标签置信度",
        },
        "text_statistics": {
            "avg_length": round(sum(text_lengths) / max(total, 1), 0),
            "min_length": min(text_lengths) if text_lengths else 0,
            "max_length": max(text_lengths) if text_lengths else 0,
            "empty_texts": sum(1 for t in text_lengths if t == 0),
        },
        "media_statistics": {
            "avg_media_per_post": round(sum(media_counts_per_post) / max(total, 1), 1),
            "max_media_per_post": max(media_counts_per_post) if media_counts_per_post else 0,
            "no_media_posts": sum(1 for m in media_counts_per_post if m == 0),
        },
    }

    return report


def main():
    parser = argparse.ArgumentParser(description="P1 迁移报告生成")
    parser.add_argument("--input", default="data/interim/candidates_v1.jsonl",
                        help="迁移后的 JSONL 文件路径")
    parser.add_argument("--id-map", default="data/interim/id_mapping_v1.json",
                        help="ID 映射表路径")
    parser.add_argument("--output", default="data/reports/migration_report.json",
                        help="报告输出路径")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    input_path = project_root / args.input
    id_map_path = project_root / args.id_map
    output_path = project_root / args.output

    print(f"📊 生成迁移报告...")
    print(f"   输入: {input_path}")
    report = generate_report(input_path, id_map_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ 报告已保存: {output_path}")

    # 打印摘要
    s = report.get("summary", {})
    print(f"\n📋 迁移摘要:")
    print(f"   总记录: {s.get('total_records', 0)}")
    print(f"   成功:   {s.get('success', 0)}")
    print(f"   降级:   {s.get('degraded', 0)}")
    if report.get("provenance_audit", {}).get("warning"):
        print(f"   ⚠️  {report['provenance_audit']['warning']}")
    if report.get("llm_review_queue", {}).get("needs_review_count", 0) > 0:
        print(f"   ⚠️  LLM 复核队列: {report['llm_review_queue']['needs_review_count']} 条")


if __name__ == "__main__":
    main()
