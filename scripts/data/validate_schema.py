#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

REQUIRED_FIELDS = [
    "schema_version",
    "post_id",
    "platform",
    "source_type",
    "blogger_id",
    "text",
    "media",
    "provenance",
    "privacy",
]

PROVENANCE_FIELDS = [
    "source_ref_hash",
    "collected_at",
    "collector",
    "terms_checked_at",
]


def validate_record(record: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field}")

    if "media" in record and not isinstance(record["media"], list):
        errors.append("media must be a list")
    if "provenance" in record and not isinstance(record["provenance"], dict):
        errors.append("provenance must be an object")
    if "privacy" in record and not isinstance(record["privacy"], dict):
        errors.append("privacy must be an object")

    provenance = record.get("provenance", {})
    if isinstance(provenance, dict):
        for field in PROVENANCE_FIELDS:
            if field not in provenance:
                errors.append(f"provenance missing field: {field}")
    return errors


def load_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main(path: str) -> int:
    path_obj = Path(path)
    if not path_obj.exists():
        print(f"ERROR: path does not exist: {path}")
        return 1

    total = 0
    invalid = 0
    for record in load_jsonl(path_obj):
        total += 1
        errors = validate_record(record)
        if errors:
            invalid += 1
            print(f"[{record.get('post_id', 'unknown')}] errors:")
            for error in errors:
                print(f"  - {error}")

    print(f"checked {total} records, invalid: {invalid}")
    return 0 if invalid == 0 else 2


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "data/interim/candidates.jsonl"))
