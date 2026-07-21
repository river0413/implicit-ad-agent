#!/usr/bin/env python3
"""合并双人标注 + 仲裁记录，生成金标数据集。
保留原始标注者证据和仲裁理由，满足 P1 可审计要求。"""
import json
from pathlib import Path
from typing import Dict, Iterable, List


def load_jsonl(path: Path) -> Iterable[Dict]:
    """加载 JSONL 文件，兼容两种格式：
    1. 标准 JSONL：每行一个完整的 JSON 对象
    2. 美化打印拼接：多个多行 JSON 对象直接拼接（如 `}\\n\\n{`）
    """
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


def merge_annotations(
    ann_a: Dict[str, Dict], ann_b: Dict[str, Dict], adjudication: Dict[str, Dict]
) -> List[Dict]:
    """合并双人标注和仲裁，输出符合 P1 金标格式的记录。
    
    规则：
    - 双方一致 → 直接采纳
    - 一方缺失 → 不进入金标（标记为 missing_one）
    - 双方分歧且已仲裁 → 采纳仲裁结果
    - 双方分歧且未仲裁 → 不进入金标
    """
    results: List[Dict] = []
    for post_id in sorted(set(ann_a) | set(ann_b)):
        rec_a = ann_a.get(post_id, {})
        rec_b = ann_b.get(post_id, {})
        adj_rec = adjudication.get(post_id, {})

        # 一方缺失则不进入金标
        if not rec_a or not rec_b:
            continue

        # 仲裁优先
        if adj_rec:
            final_label = adj_rec.get("label", "")
            conflict_reason = adj_rec.get("conflict_reason", "")
            arbiter = adj_rec.get("arbiter", "")
            arbiter_note = adj_rec.get("arbiter_note", "")
            adjudicated = True
        elif rec_a.get("label") == rec_b.get("label"):
            final_label = rec_a["label"]
            conflict_reason = ""
            arbiter = ""
            arbiter_note = ""
            adjudicated = False
        else:
            # 分歧且未仲裁 → 不进入金标
            continue

        record = {
            "post_id": post_id,
            "label": final_label,
            "annotator_a": {
                "id": rec_a.get("annotator_id", ""),
                "label": rec_a.get("label", ""),
                "confidence": rec_a.get("confidence"),
                "evidence_codes": rec_a.get("evidence_codes", []),
                "evidence": rec_a.get("evidence", []),
            },
            "annotator_b": {
                "id": rec_b.get("annotator_id", ""),
                "label": rec_b.get("label", ""),
                "confidence": rec_b.get("confidence"),
                "evidence_codes": rec_b.get("evidence_codes", []),
                "evidence": rec_b.get("evidence", []),
            },
            "adjudicated": adjudicated,
        }
        if adjudicated:
            record["adjudication"] = {
                "label": final_label,
                "conflict_reason": conflict_reason,
                "arbiter": arbiter,
                "arbiter_note": arbiter_note,
            }
        results.append(record)
    return results


def write_jsonl(records: Iterable[Dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(path_a: str, path_b: str, adjudication_path: str, output_path: str) -> None:
    ann_a = {r["post_id"]: r for r in load_jsonl(Path(path_a))}
    ann_b = {r["post_id"]: r for r in load_jsonl(Path(path_b))}
    adjudication = {r["post_id"]: r for r in load_jsonl(Path(adjudication_path))}
    gold = merge_annotations(ann_a, ann_b, adjudication)
    write_jsonl(gold, Path(output_path))

    label_counts = {}
    for r in gold:
        label_counts[r["label"]] = label_counts.get(r["label"], 0) + 1
    adj_count = sum(1 for r in gold if r["adjudicated"])

    print(f"gold records: {len(gold)}  (adjudicated: {adj_count})")
    print(f"label distribution: {label_counts}")
    print(f"saved to {output_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 5:
        print("usage: python build_gold_dataset.py a.jsonl b.jsonl adjudication.jsonl gold_v1.jsonl")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
