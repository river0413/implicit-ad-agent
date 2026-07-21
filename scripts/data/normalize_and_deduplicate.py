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
    """计算记录指纹用于去重（基于 title + text + media source_urls）。"""
    normalized = {
        "title": normalize_text(record.get("title") or ""),
        "text": normalize_text(record.get("text", "")),
        "media_urls": sorted([
            m.get("source_url", "") for m in record.get("media", []) if isinstance(m, dict)
        ]),
        "platform": record.get("platform"),
    }
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> Iterable[Dict]:
    """加载 JSONL 文件，兼容两种格式：
    1. 标准 JSONL：每行一个完整的 JSON 对象
    2. 美化打印拼接：多个多行 JSON 对象直接拼接（如 `}\\n\\n{`）
    """
    with path.open("r", encoding="utf-8-sig") as stream:
        content = stream.read()

    decoder = json.JSONDecoder()
    idx = 0
    content_len = len(content)
    while idx < content_len:
        # 跳过空白字符
        while idx < content_len and content[idx] in " \t\n\r":
            idx += 1
        if idx >= content_len:
            break
        try:
            obj, end = decoder.raw_decode(content, idx)
            yield obj
            idx = end
        except json.JSONDecodeError as e:
            # 打印上下文便于排查，然后跳过该位置继续
            context = content[max(0, idx - 40):idx + 80]
            raise json.JSONDecodeError(
                f"Failed to decode JSON at position {idx}: {e.msg}. Context: ...{context!r}...",
                e.doc, e.pos
            ) from e


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
    input_path = sys.argv[1] if len(sys.argv) > 1 else r"data\run_outputs\anonymized_posts.jsonl"
    output_path = sys.argv[2] if len(sys.argv) > 2 else r"data\run_outputs\anonymized_postsn.jsonl"
    main(input_path, output_path)
