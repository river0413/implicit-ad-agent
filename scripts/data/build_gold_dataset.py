#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Dict, Iterable, List


def load_jsonl(path: Path) -> Iterable[Dict]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def merge_annotations(ann_a: Dict[str, Dict], ann_b: Dict[str, Dict], adjudication: Dict[str, str]) -> List[Dict]:
    results: List[Dict] = []
    for post_id in sorted(set(ann_a) | set(ann_b)):
        if post_id in adjudication:
            final_label = adjudication[post_id]
        elif post_id in ann_a and post_id in ann_b and ann_a[post_id]["label"] == ann_b[post_id]["label"]:
            final_label = ann_a[post_id]["label"]
        else:
            continue

        record = {
            "post_id": post_id,
            "label": final_label,
            "source_labels": {
                "annotator_a": ann_a.get(post_id, {}).get("label"),
                "annotator_b": ann_b.get(post_id, {}).get("label"),
            },
        }
        if post_id in adjudication:
            record["adjudicated"] = True
            record["adjudication_label"] = adjudication[post_id]
        else:
            record["adjudicated"] = False
        results.append(record)
    return results


def write_jsonl(records: Iterable[Dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(path_a: str, path_b: str, adjudication_path: str, output_path: str) -> None:
    ann_a = {r["post_id"]: r for r in load_jsonl(Path(path_a))}
    ann_b = {r["post_id"]: r for r in load_jsonl(Path(path_b))}
    adjudication = {r["post_id"]: r["label"] for r in load_jsonl(Path(adjudication_path))}
    gold = merge_annotations(ann_a, ann_b, adjudication)
    write_jsonl(gold, Path(output_path))
    print(f"wrote {len(gold)} gold records to {output_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 5:
        print("usage: python build_gold_dataset.py path_a.jsonl path_b.jsonl adjudication.jsonl gold_v1.jsonl")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
