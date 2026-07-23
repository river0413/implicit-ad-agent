#!/usr/bin/env python3
"""按 blogger/creator 分组划分 train/dev/test，含 content_group 约束防泄漏。

v1.1 改进：
  - 以 blogger_id 为最小分组单位
  - 同一 content_group_id 的帖子强制分配到同一划分，防止跨平台转载泄漏
  - 输出划分报告

用法：
  python scripts/data/split_by_blogger.py gold_v1.jsonl train_ids.txt dev_ids.txt test_ids.txt
  python scripts/data/split_by_blogger.py gold_v1.jsonl train_ids.txt dev_ids.txt test_ids.txt --report data/reports/split_report.json
"""
import json
import random
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
        except json.JSONDecodeError:
            next_brace = raw_text.find("{", idx + 1)
            if next_brace == -1:
                break
            idx = next_brace


def write_ids(post_ids: List[str], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for post_id in post_ids:
            stream.write(post_id + "\n")


def build_split_groups(records: List[Dict]) -> Dict[str, List[str]]:
    """构建划分组，以 blogger_id 为最小分组，同时考虑 content_group_id 约束。
    
    逻辑：
    1. 首先按 blogger_id 建组
    2. 收集所有含 content_group_id 的帖子
    3. 将同一 content_group_id 的帖子强制放入同一组（取第一个出现的 blogger_id 的组）
    4. 合并 blogger 组（同 content_group 的帖子合并到同一 blogger 组）
    
    Returns: {group_key: [post_id, ...]}
    """
    # Step 1: 按 blogger_id 分组
    blogger_groups: Dict[str, List[str]] = defaultdict(list)
    for record in records:
        bid = record.get("blogger_id", "unknown")
        pid = record.get("post_id", "")
        if pid:
            blogger_groups[bid].append(pid)

    # Step 2: 收集 content_group 映射
    content_groups: Dict[str, List[str]] = defaultdict(list)
    pid_to_content_group: Dict[str, str] = {}
    for record in records:
        cg = record.get("content_group_id")
        pid = record.get("post_id", "")
        if cg and pid:
            content_groups[cg].append(pid)
            pid_to_content_group[pid] = cg

    # Step 3: 将同 content_group 的帖子分配到同一个 blogger 组
    # 找到每个 content_group 中第一个帖子的 blogger_id，将整组帖子归入该 blogger 组
    pid_to_blogger: Dict[str, str] = {}
    for bid, pids in blogger_groups.items():
        for pid in pids:
            pid_to_blogger[pid] = bid

    # 合并：对于每个 content_group，找到"主宰 blogger 组"并合并
    merged_blogger_groups: Dict[str, set] = {bid: set(pids) for bid, pids in blogger_groups.items()}
    cg_assignments: Dict[str, str] = {}  # cg → master_blogger

    for cg, pids in content_groups.items():
        # 找到该 content_group 中最常见的 blogger
        blogger_votes = defaultdict(int)
        for pid in pids:
            bid = pid_to_blogger.get(pid, "unknown")
            blogger_votes[bid] += 1
        if blogger_votes:
            master_blogger = max(blogger_votes, key=blogger_votes.get)
            cg_assignments[cg] = master_blogger
            # 将同 content_group 的帖子从其他 blogger 组移入 master 组
            for pid in pids:
                orig_bid = pid_to_blogger.get(pid, "unknown")
                if orig_bid != master_blogger and orig_bid in merged_blogger_groups:
                    merged_blogger_groups[orig_bid].discard(pid)
                merged_blogger_groups[master_blogger].add(pid)

    # 转回 list
    return {bid: list(pids) for bid, pids in merged_blogger_groups.items()}


def split_groups(
    groups: Dict[str, List[str]],
    ratios: Tuple[float, float, float] = (0.7, 0.15, 0.15),
    seed: int = 42,
) -> Tuple[Dict[str, List[str]], Dict]:
    """按比例划分组到 train/dev/test。
    
    使用贪心算法：每次将当前最小的划分分配新组。
    """
    random.seed(seed)
    target_train, target_dev, target_test = ratios

    assignments = {"train": [], "dev": [], "test": []}
    group_items = list(groups.items())
    random.shuffle(group_items)

    for group_key, post_ids in group_items:
        # 选择当前占比最小的划分
        current = {key: len(ids) for key, ids in assignments.items()}
        target = {"train": target_train, "dev": target_dev, "test": target_test}
        
        # 计算当前偏差
        total = sum(current.values()) + len(post_ids)
        if total == 0:
            to_assign = "train"
        else:
            deviations = {
                key: (current[key] + (len(post_ids) if key == "train" else 0)) / max(total, 1) - target[key]
                for key in assignments
            }
            to_assign = min(deviations, key=lambda k: deviations[k])
        
        assignments[to_assign].extend(post_ids)

    # 统计
    stats = {
        "total_posts": sum(len(v) for v in assignments.values()),
        "total_groups": len(groups),
        "train_posts": len(assignments["train"]),
        "dev_posts": len(assignments["dev"]),
        "test_posts": len(assignments["test"]),
        "train_pct": round(len(assignments["train"]) / max(sum(len(v) for v in assignments.values()), 1) * 100, 1),
        "dev_pct": round(len(assignments["dev"]) / max(sum(len(v) for v in assignments.values()), 1) * 100, 1),
        "test_pct": round(len(assignments["test"]) / max(sum(len(v) for v in assignments.values()), 1) * 100, 1),
    }

    return assignments, stats


def main(input_path: str, train_path: str, dev_path: str, test_path: str,
         report_path: Optional[str] = None, seed: int = 42) -> None:
    records = list(load_jsonl(Path(input_path)))
    groups = build_split_groups(records)

    # 输出 content_group 约束信息
    cg_count = sum(1 for r in records if r.get("content_group_id"))
    print(f"📊 划分前分析:")
    print(f"   总帖子:     {len(records)}")
    print(f"   博主组:     {len(groups)}")
    print(f"   content_group 约束: {cg_count} 条帖子受约束")

    splits, stats = split_groups(groups, seed=seed)
    write_ids(splits["train"], Path(train_path))
    write_ids(splits["dev"], Path(dev_path))
    write_ids(splits["test"], Path(test_path))

    print(f"\n✅ 划分完成:")
    print(f"   train: {stats['train_posts']} ({stats['train_pct']}%)")
    print(f"   dev:   {stats['dev_posts']} ({stats['dev_pct']}%)")
    print(f"   test:  {stats['test_posts']} ({stats['test_pct']}%)")

    # 泄漏检查
    train_ids = set(splits["train"])
    dev_ids = set(splits["dev"])
    test_ids = set(splits["test"])
    train_dev_overlap = train_ids & dev_ids
    train_test_overlap = train_ids & test_ids
    dev_test_overlap = dev_ids & test_ids
    if train_dev_overlap or train_test_overlap or dev_test_overlap:
        print(f"\n⚠️  泄漏警告:")
        if train_dev_overlap:
            print(f"   train ∩ dev: {len(train_dev_overlap)}")
        if train_test_overlap:
            print(f"   train ∩ test: {len(train_test_overlap)}")
        if dev_test_overlap:
            print(f"   dev ∩ test: {len(dev_test_overlap)}")

    # 保存报告
    if report_path:
        rp = Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        report = {
            **stats,
            "content_group_constrained_posts": cg_count,
            "blogger_groups": len(groups),
            "leakage": {
                "train_dev_overlap": len(train_dev_overlap),
                "train_test_overlap": len(train_test_overlap),
                "dev_test_overlap": len(dev_test_overlap),
            },
            "seed": seed,
        }
        with rp.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"📝 报告: {rp}")


if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="按博主+content_group分组划分 train/dev/test")
    parser.add_argument("input", help="金标 JSONL 输入文件")
    parser.add_argument("train", help="train ID 输出文件")
    parser.add_argument("dev", help="dev ID 输出文件")
    parser.add_argument("test", help="test ID 输出文件")
    parser.add_argument("--report", default=None, help="划分报告输出路径")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()
    main(args.input, args.train, args.dev, args.test, args.report, args.seed)
