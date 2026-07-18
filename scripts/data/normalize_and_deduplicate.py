#!/usr/bin/env python3
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#@]\w+", "", text)
    return text


def record_fingerprint(record: Dict) -> str:
    normalized = {
        "text": normalize_text(record.get("text", "")),
        "media": record.get("media", []),
        "platform": record.get("platform"),
    }
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> Iterable[Dict]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_jsonl(records: Iterable[Dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def deduplicate(records: Iterable[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for record in records:
        fingerprint = record_fingerprint(record)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        record["text"] = normalize_text(record.get("text", ""))
        unique.append(record)
    return unique


def main(input_path: str, output_path: str) -> None:
    src = Path(input_path)
    dst = Path(output_path)
    records = list(load_jsonl(src))
    unique = deduplicate(records)
    write_jsonl(unique, dst)
    print(f"deduplicated {len(records)} → {len(unique)} records")


if __name__ == "__main__":
    import sys
    input_path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/candidates.jsonl"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "data/interim/candidates_dedup.jsonl"
    main(input_path, output_path)
