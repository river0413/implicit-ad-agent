#!/usr/bin/env python3
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def load_jsonl(path: Path) -> Iterable[Dict]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_ids(post_ids: List[str], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for post_id in post_ids:
            stream.write(post_id + "\n")


def split_groups(groups: Dict[str, List[str]], ratios: Tuple[float, float, float]) -> Dict[str, List[str]]:
    target_train, target_dev, target_test = ratios
    assignments = {"train": [], "dev": [], "test": []}
    group_items = list(groups.items())
    random.shuffle(group_items)
    for blogger_id, post_ids in group_items:
        current = {key: len(ids) for key, ids in assignments.items()}
        to_assign = min(current, key=current.get)
        assignments[to_assign].extend(post_ids)
    return assignments


def main(input_path: str, train_path: str, dev_path: str, test_path: str) -> None:
    records = list(load_jsonl(Path(input_path)))
    groups: Dict[str, List[str]] = defaultdict(list)
    for record in records:
        groups[record.get("blogger_id", "unknown")].append(record["post_id"])

    splits = split_groups(groups, (0.7, 0.15, 0.15))
    write_ids(splits["train"], Path(train_path))
    write_ids(splits["dev"], Path(dev_path))
    write_ids(splits["test"], Path(test_path))
    print(f"wrote train={len(splits['train'])}, dev={len(splits['dev'])}, test={len(splits['test'])}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 5:
        print("usage: python split_by_blogger.py gold_v1.jsonl train_ids.txt dev_ids.txt test_ids.txt")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
