#!/usr/bin/env python3
"""计算两名标注者之间的 Cohen's κ 及 95% bootstrap 置信区间。"""
import json
import random
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

LABELS = ["明广", "暗广", "非广"]
LABEL_INDEX = {label: idx for idx, label in enumerate(LABELS)}


def load_annotations(path: Path) -> Dict[str, str]:
    """从 JSONL 加载标注，返回 {post_id: label}。

    兼容两种格式：
      - 标准 JSONL（每行一个完整 JSON 对象）
      - 美化打印拼接的 JSON（每个对象跨多行）
    """
    data: Dict[str, str] = {}
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
            data[obj["post_id"]] = obj["label"]
            idx = end
        except json.JSONDecodeError:
            next_brace = raw_text.find("{", idx + 1)
            if next_brace == -1:
                break
            idx = next_brace
    return data


def _cohen_kappa_from_arrays(a: List[int], b: List[int]) -> float:
    """计算 Cohen's κ。"""
    n = len(a)
    if n == 0:
        return 0.0
    conf = Counter(zip(a, b))
    p0 = sum(conf[(i, i)] for i in range(len(LABELS))) / n
    pa = [sum(conf[(i, j)] for j in range(len(LABELS))) / n for i in range(len(LABELS))]
    pb = [sum(conf[(i, j)] for i in range(len(LABELS))) / n for j in range(len(LABELS))]
    pe = sum(pa[i] * pb[i] for i in range(len(LABELS)))
    if pe == 1.0:
        return 1.0
    return (p0 - pe) / (1 - pe)


def cohen_kappa_ci(a: List[int], b: List[int], n_bootstrap: int = 2000) -> Tuple[float, float, float]:
    """返回 (kappa, lower_95, upper_95)。"""
    kappa = _cohen_kappa_from_arrays(a, b)
    n = len(a)
    pairs = list(zip(a, b))
    bootstraps = []
    for _ in range(n_bootstrap):
        sample = [pairs[random.randint(0, n - 1)] for _ in range(n)]
        sa, sb = zip(*sample)
        bootstraps.append(_cohen_kappa_from_arrays(list(sa), list(sb)))
    bootstraps.sort()
    lower = bootstraps[int(0.025 * n_bootstrap)]
    upper = bootstraps[int(0.975 * n_bootstrap)]
    return kappa, lower, upper


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

    kappa, ci_low, ci_high = cohen_kappa_ci(labels_a, labels_b)
    matrix = build_confusion_matrix(labels_a, labels_b)

    print(f"common samples: {len(common_ids)}")
    print(f"Cohen's κ: {kappa:.4f}  (95% CI: {ci_low:.4f} – {ci_high:.4f})\n")
    print("confusion matrix (rows=A, cols=B)")
    print("\t" + "\t".join(LABELS))
    for label, row in zip(LABELS, matrix):
        print(label + "\t" + "\t".join(str(x) for x in row))

    # 各类别一致率
    print("\nper-class agreement:")
    for i, label in enumerate(LABELS):
        total_a = sum(matrix[i])
        agreed = matrix[i][i]
        rate = agreed / total_a if total_a else 0
        print(f"  {label}: {agreed}/{total_a} = {rate:.1%}")

    # 分歧详情
    print("\n--- 分歧样本 ---")
    for post_id in common_ids:
        if a[post_id] == b[post_id]:
            continue
        print(f"  {post_id}: A={a[post_id]}  B={b[post_id]}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("usage: python calculate_agreement.py path_a.jsonl path_b.jsonl")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])
