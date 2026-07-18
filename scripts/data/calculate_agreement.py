#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

LABELS = ["明广", "暗广", "非广"]
LABEL_INDEX = {label: idx for idx, label in enumerate(LABELS)}


def load_annotations(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            post_id = record["post_id"]
            label = record["label"]
            data[post_id] = label
    return data


def cohen_kappa(a: List[int], b: List[int]) -> float:
    assert len(a) == len(b)
    n = len(a)
    if n == 0:
        return 0.0
    conf = Counter(zip(a, b))
    p0 = sum(count for count in conf.values() if count and list(conf.keys())[0] is not None) / n
    p0 = sum(conf[(i, i)] for i in range(len(LABELS))) / n
    pa = [sum(conf[(i, j)] for j in range(len(LABELS))) / n for i in range(len(LABELS))]
    pb = [sum(conf[(i, j)] for i in range(len(LABELS))) / n for j in range(len(LABELS))]
    pe = sum(pa[i] * pb[i] for i in range(len(LABELS)))
    return (p0 - pe) / (1 - pe) if pe != 1 else 1.0


def build_confusion_matrix(a: List[int], b: List[int]) -> List[List[int]]:
    matrix = [[0] * len(LABELS) for _ in LABELS]
    for i, j in zip(a, b):
        matrix[i][j] += 1
    return matrix


def main(path_a: str, path_b: str) -> None:
    a = load_annotations(Path(path_a))
    b = load_annotations(Path(path_b))
    common_ids = sorted(set(a) & set(b))
    if not common_ids:
        print("no overlapping post_id between annotations")
        return

    labels_a = [LABEL_INDEX[a[post_id]] for post_id in common_ids]
    labels_b = [LABEL_INDEX[b[post_id]] for post_id in common_ids]
    kappa = cohen_kappa(labels_a, labels_b)
    matrix = build_confusion_matrix(labels_a, labels_b)

    print(f"common samples: {len(common_ids)}")
    print(f"Cohen's kappa: {kappa:.4f}\n")
    print("confusion matrix (rows: A, cols: B)")
    print("\t" + "\t".join(LABELS))
    for label, row in zip(LABELS, matrix):
        print(label + "\t" + "\t".join(str(x) for x in row))


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("usage: python calculate_agreement.py path_a.jsonl path_b.jsonl")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])
