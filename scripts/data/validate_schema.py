#!/usr/bin/env python3
"""Schema 校验器 —— 检查爬虫产出的 JSONL 是否满足最小字段规范。

新版 schema（v2，精简后）：
  必填：post_id, platform, blogger_id, title, text, media, comments, blogger_history_refs
  可选：published_at (null 表示未知)
  media[] 可选：caption (LLM 提取的图片标注), is_content (是否为内容图)
  元数据：_collected (source_url, collected_at, collector)
  _collected 可选：llm_verified, llm_needs_review, llm_confidence, llm_review_reason
"""
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

# ── 新版必填字段 ──
REQUIRED_FIELDS = [
    "post_id",
    "platform",
    "blogger_id",
    "title",          # 可为 null（提取不到标题时）
    "text",
    "media",
    "comments",
    "blogger_history_refs",
]

# ── 采集元数据（_collected 内部必填）──
COLLECTED_FIELDS = [
    "source_url",
    "collected_at",
    "collector",
]


def validate_record(record: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    pid = record.get("post_id", "?")

    # 1. 必填字段存在性
    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"missing required field: {field}")

    # 2. 类型校验
    if "media" in record and not isinstance(record["media"], list):
        errors.append("media must be a list")
    if "comments" in record and not isinstance(record["comments"], list):
        errors.append("comments must be a list")
    if "blogger_history_refs" in record and not isinstance(record["blogger_history_refs"], list):
        errors.append("blogger_history_refs must be a list")

    # 3. media 内部结构校验
    for i, m in enumerate(record.get("media", [])):
        if not isinstance(m, dict):
            errors.append(f"media[{i}] must be an object")
            continue
        if "source_url" not in m:
            errors.append(f"media[{i}] missing source_url")

    # 4. comments 内部结构校验（如有）
    for i, c in enumerate(record.get("comments", [])):
        if not isinstance(c, dict):
            errors.append(f"comments[{i}] must be an object")
            continue
        for f in ("comment_id", "text", "created_at", "author_id"):
            if f not in c:
                errors.append(f"comments[{i}] missing {f}")

    # 5. blogger_history_refs 内部校验（应为字符串列表）
    for i, h in enumerate(record.get("blogger_history_refs", [])):
        if not isinstance(h, str):
            errors.append(f"blogger_history_refs[{i}] must be a string (post_id)")

    # 6. 采集元数据
    collected = record.get("_collected", {})
    if not isinstance(collected, dict):
        errors.append("_collected must be an object")
    else:
        for field in COLLECTED_FIELDS:
            if field not in collected:
                errors.append(f"_collected missing field: {field}")

    return errors


def load_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
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
