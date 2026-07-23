#!/usr/bin/env python3
"""计算两名标注者之间的 Cohen's κ 及 95% bootstrap 置信区间。

v1.1 改进：
  - κ 只基于两人原始三元标签（明广/暗广/非广）
  - uncertain/out_of_scope 单独统计，不计入 κ
  - 输出完整分歧分析
"""
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

LABELS = ["明广", "暗广", "非广"]
LABEL_INDEX = {label: idx for idx, label in enumerate(LABELS)}
SPECIAL_LABELS = {"uncertain", "out_of_scope"}


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
    rng = random.Random(42)
    for _ in range(n_bootstrap):
        sample = [pairs[rng.randint(0, n - 1)] for _ in range(n)]
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


def analyze_disagreements(
    a_labels: List[str], b_labels: List[str], common_ids: List[str]
) -> Dict:
    """分析分歧集中的模式。"""
    disagreements = []
    for pid, la, lb in zip(common_ids, a_labels, b_labels):
        if la != lb:
            disagreements.append({
                "post_id": pid,
                "label_a": la,
                "label_b": lb,
            })

    # 分歧类型分布
    type_counts = defaultdict(int)
    for d in disagreements:
        pair = tuple(sorted([d["label_a"], d["label_b"]]))
        type_counts[str(pair)] += 1

    return {
        "total_disagreements": len(disagreements),
        "disagreement_types": dict(type_counts),
        "disagreement_samples": disagreements[:20],  # 前 20 条
    }


def main(path_a: str, path_b: str) -> None:
    a = load_annotations(Path(path_a))
    b = load_annotations(Path(path_b))
    common_ids = sorted(set(a) & set(b))
    if not common_ids:
        print("no overlapping post_id between annotations")
        return

    # 分离有效标签和特殊标签
    valid_ids = []
    special_stats = defaultdict(lambda: {"a": 0, "b": 0, "both": 0})

    for pid in common_ids:
        la = a[pid]
        lb = b[pid]
        if la in SPECIAL_LABELS or lb in SPECIAL_LABELS:
            key = f"a={la}, b={lb}" if la != lb else la
            if la in SPECIAL_LABELS:
                special_stats[la]["a" if lb not in SPECIAL_LABELS else "both"] += 1
            if lb in SPECIAL_LABELS:
                special_stats[lb]["b" if la not in SPECIAL_LABELS else "both"] += 1
            # "both" case handled above; normalize
        else:
            valid_ids.append(pid)

    # ── κ 计算（仅有效三元标签）──
    labels_a = [LABEL_INDEX[a[pid]] for pid in valid_ids]
    labels_b = [LABEL_INDEX[b[pid]] for pid in valid_ids]

    kappa, ci_low, ci_high = cohen_kappa_ci(labels_a, labels_b)
    matrix = build_confusion_matrix(labels_a, labels_b)

    # 原始一致率
    raw_agreement = sum(1 for i, j in zip(labels_a, labels_b) if i == j) / max(len(labels_a), 1)

    # 分歧分析
    disagreement_analysis = analyze_disagreements(
        [a[pid] for pid in valid_ids],
        [b[pid] for pid in valid_ids],
        valid_ids,
    )

    print(f"📊 标注一致性分析")
    print(f"{'='*60}")
    print(f"   共同标注样本: {len(common_ids)}")
    print(f"   有效三元标签: {len(valid_ids)} (用于 κ 计算)")
    print(f"   Cohen's κ:    {kappa:.4f}  (95% CI: {ci_low:.4f} – {ci_high:.4f})")
    print(f"   原始一致率:   {raw_agreement:.1%}")
    print(f"")

    print(f"confusion matrix (rows=A, cols=B)")
    print(f"\t" + "\t".join(LABELS))
    for label, row in zip(LABELS, matrix):
        print(f"{label}\t" + "\t".join(str(x) for x in row))

    print(f"\n📋 特殊标签统计 (不计入 κ):")
    for label in sorted(SPECIAL_LABELS):
        s = special_stats.get(label, {})
        print(f"   {label}: A={s.get('a', 0)}, B={s.get('b', 0)}, both={s.get('both', 0)}")

    print(f"\n🔍 分歧分析:")
    print(f"   分歧样本: {disagreement_analysis['total_disagreements']}")
    if disagreement_analysis["disagreement_types"]:
        print(f"   分歧类型:")
        for pair, count in sorted(disagreement_analysis["disagreement_types"].items()):
            print(f"     {pair}: {count}")

    # κ 阈值检查
    if kappa < 0.6:
        print(f"\n⚠️  κ = {kappa:.4f} < 0.6，标注一致性未达标。建议复盘分歧并修订标注指南。")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("usage: python calculate_agreement.py annotator_a.jsonl annotator_b.jsonl")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])

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
