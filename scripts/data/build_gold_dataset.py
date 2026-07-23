#!/usr/bin/env python3
"""合并双人标注 + 仲裁记录，生成金标数据集。

保留原始标注者证据和仲裁理由，满足 P1 可审计要求。

v1.1 改进：
  - 分歧样本必须有仲裁才进入金标；未仲裁分歧不进入
  - uncertain/out_of_scope 单独统计，默认不进 gold
  - 置信度 <0.6 的样本进入复核队列
  - 输出 excluded 记录供审查
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def load_jsonl(path: Path) -> Iterable[Dict]:
    """加载 JSONL 文件，兼容标准 JSONL 和美化打印拼接格式。"""
    raw_text = path.read_text(encoding="utf-8-sig")
    decoder = json.JSONDecoder()
    idx = 0
    content_len = len(raw_text)
    while idx < content_len:
        while idx < content_len and raw_text[idx] in " \t\n\r":
            idx += 1
        if idx >= content_len:
            break
        try:
            obj, end = decoder.raw_decode(raw_text, idx)
            yield obj
            idx = end
        except json.JSONDecodeError as e:
            context = raw_text[max(0, idx - 40):idx + 80]
            raise json.JSONDecodeError(
                f"Failed to decode JSON at position {idx}: {e.msg}. Context: ...{context!r}...",
                e.doc, e.pos,
            ) from e


def _is_valid_gold_label(label: str) -> bool:
    """检查标签是否可进入金标。uncertain/out_of_scope 默认不进 gold。"""
    return label in ("明广", "暗广", "非广")


def merge_annotations(
    ann_a: Dict[str, Dict],
    ann_b: Dict[str, Dict],
    adjudication: Dict[str, Dict],
    min_confidence: float = 0.6,
) -> Tuple[List[Dict], List[Dict]]:
    """合并双人标注和仲裁，输出符合 P1 金标格式的记录。

    规则：
    - 双方一致 → 直接采纳
    - 一方缺失 → 不进入金标
    - 双方分歧且已仲裁 → 采纳仲裁结果
    - 双方分歧且未仲裁 → 不进入金标（标记为 excluded）
    - uncertain / out_of_scope → 不进入金标（单独统计）
    - 置信度 < min_confidence → 进入复核队列

    Returns:
        (gold_records, excluded_records)
    """
    gold: List[Dict] = []
    excluded: List[Dict] = []

    for post_id in sorted(set(ann_a) | set(ann_b)):
        rec_a = ann_a.get(post_id, {})
        rec_b = ann_b.get(post_id, {})
        adj_rec = adjudication.get(post_id, {})

        # 一方缺失则不进入金标
        if not rec_a or not rec_b:
            excluded.append({
                "post_id": post_id,
                "reason": "missing_one_annotator",
                "annotator_a": rec_a.get("annotator_id") if rec_a else None,
                "annotator_b": rec_b.get("annotator_id") if rec_b else None,
            })
            continue

        label_a = rec_a.get("label", "")
        label_b = rec_b.get("label", "")

        # uncertain / out_of_scope 不进入 gold
        if label_a in ("uncertain", "out_of_scope") or label_b in ("uncertain", "out_of_scope"):
            excluded.append({
                "post_id": post_id,
                "reason": "uncertain_or_out_of_scope",
                "label_a": label_a,
                "label_b": label_b,
            })
            continue

        # 仲裁优先
        if adj_rec:
            final_label = adj_rec.get("label", "")
            if not _is_valid_gold_label(final_label):
                excluded.append({
                    "post_id": post_id,
                    "reason": f"adjudicated_label_invalid: {final_label}",
                })
                continue
            conflict_reason = adj_rec.get("conflict_reason", "")
            arbiter = adj_rec.get("arbiter", "")
            arbiter_note = adj_rec.get("arbiter_note", "")
            adjudicated = True
        elif label_a == label_b:
            if not _is_valid_gold_label(label_a):
                excluded.append({
                    "post_id": post_id,
                    "reason": f"agreed_label_invalid: {label_a}",
                })
                continue
            final_label = label_a
            conflict_reason = ""
            arbiter = ""
            arbiter_note = ""
            adjudicated = False
        else:
            # 分歧且未仲裁 → 不进入金标
            excluded.append({
                "post_id": post_id,
                "reason": "disagreement_not_adjudicated",
                "label_a": label_a,
                "label_b": label_b,
            })
            continue

        # 低置信度标记
        conf_a = rec_a.get("confidence", 1.0) or 1.0
        conf_b = rec_b.get("confidence", 1.0) or 1.0
        low_confidence = (conf_a < min_confidence) or (conf_b < min_confidence)

        record = {
            "post_id": post_id,
            "label": final_label,
            "annotator_a": {
                "id": rec_a.get("annotator_id", ""),
                "label": label_a,
                "confidence": rec_a.get("confidence"),
                "evidence_codes": rec_a.get("evidence_codes", []),
                "evidence": rec_a.get("evidence", []),
            },
            "annotator_b": {
                "id": rec_b.get("annotator_id", ""),
                "label": label_b,
                "confidence": rec_b.get("confidence"),
                "evidence_codes": rec_b.get("evidence_codes", []),
                "evidence": rec_b.get("evidence", []),
            },
            "adjudicated": adjudicated,
            "low_confidence": low_confidence,
        }
        if adjudicated:
            record["adjudication"] = {
                "label": final_label,
                "conflict_reason": conflict_reason,
                "arbiter": arbiter,
                "arbiter_note": arbiter_note,
            }
        gold.append(record)

    return gold, excluded


def write_jsonl(records: Iterable[Dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(path_a: str, path_b: str, adjudication_path: str,
         output_path: str, excluded_path: Optional[str] = None,
         min_confidence: float = 0.6) -> None:
    ann_a = {r["post_id"]: r for r in load_jsonl(Path(path_a))}
    ann_b = {r["post_id"]: r for r in load_jsonl(Path(path_b))}

    adjudication = {}
    adj_path = Path(adjudication_path)
    if adj_path.exists():
        adjudication = {r["post_id"]: r for r in load_jsonl(adj_path)}

    gold, excluded = merge_annotations(ann_a, ann_b, adjudication, min_confidence)
    write_jsonl(gold, Path(output_path))

    # 标签分布
    label_counts = defaultdict(int)
    for r in gold:
        label_counts[r["label"]] += 1
    adj_count = sum(1 for r in gold if r["adjudicated"])
    low_conf_count = sum(1 for r in gold if r.get("low_confidence"))

    # 排除原因分布
    exclude_reasons = defaultdict(int)
    for r in excluded:
        exclude_reasons[r["reason"]] += 1

    print(f"📊 金标构建完成:")
    print(f"   gold records:     {len(gold)}")
    print(f"     adjudicated:    {adj_count}")
    print(f"     low_confidence: {low_conf_count}")
    print(f"   excluded:         {len(excluded)}")
    print(f"   label distribution: {dict(label_counts)}")
    if exclude_reasons:
        print(f"   exclusion reasons:  {dict(exclude_reasons)}")
    print(f"   saved to:         {output_path}")

    # 保存排除记录
    if excluded_path:
        ep = Path(excluded_path)
        ep.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(excluded, ep)
        print(f"   excluded saved to: {ep}")

    # 警告
    if adj_count == 0 and any(
        ann_a.get(pid, {}).get("label") != ann_b.get(pid, {}).get("label")
        for pid in set(ann_a) & set(ann_b)
    ):
        print(f"\n⚠️  警告: 存在分歧样本但无仲裁记录。这些样本将被排除。")
    if low_conf_count > 0:
        print(f"⚠️  警告: {low_conf_count} 条金标记录置信度 < {min_confidence}，需复核。")


if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="构建金标数据集（含不确定排除和仲裁要求）")
    parser.add_argument("annotator_a", help="标注者 A 的标注文件")
    parser.add_argument("annotator_b", help="标注者 B 的标注文件")
    parser.add_argument("adjudication", help="仲裁文件")
    parser.add_argument("output", help="金标输出文件")
    parser.add_argument("--excluded-output", default=None, help="排除记录输出路径")
    parser.add_argument("--min-confidence", type=float, default=0.6,
                        help="最低置信度阈值（默认 0.6）")
    args = parser.parse_args()
    main(args.annotator_a, args.annotator_b, args.adjudication,
         args.output, args.excluded_output, args.min_confidence)
