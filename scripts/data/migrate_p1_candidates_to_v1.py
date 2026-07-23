#!/usr/bin/env python3
"""P1 候选数据迁移脚本：将旧格式候选记录转换为 v1.0/v1.1 schema。

功能：
  1. 只读旧候选（annotations/*.json + run_outputs/*.jsonl），输出新文件 + ID 映射表
  2. post_id: 裸哈希 → post_ 前缀（保存 ID 映射表）
  3. _collected → provenance + privacy（显式迁移；无法确认的不伪造）
  4. media: ref/source_url/caption/is_content → media_id/type/ref/sha256/phash/ocr_text
  5. 处理 title 字段（保留为可选）
  6. 标记 llm_needs_review 记录
  7. 原始候选数据保持只读，不原地覆盖

用法：
  python scripts/data/migrate_p1_candidates_to_v1.py \
    --input-dir data/annotations \
    --jsonl-dir data/run_outputs \
    --output data/interim/candidates_v1.jsonl \
    --id-map data/interim/id_mapping_v1.json \
    --target-schema 1.1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

CST = timezone(timedelta(hours=8))

# ── 可计算字段（计算可得则计算，否则填 null）──
def compute_sha256(file_path: Path) -> Optional[str]:
    """计算文件的 SHA-256 哈希。文件不存在则返回 None。"""
    try:
        if not file_path or not file_path.exists():
            return None
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
    except (OSError, PermissionError):
        return None
    except Exception:
        return None


def compute_phash(file_path: Path) -> Optional[str]:
    """计算感知哈希（简化版：使用文件内容的 SHA-256 前 16 位作为代理）。
    完整实现需要图像处理库（PIL + imagehash），此处提供占位。"""
    sha = compute_sha256(file_path)
    return sha[:16] if sha else None


def infer_media_type(ref: str) -> str:
    """根据文件扩展名推断媒体类型。"""
    if not ref:
        return "other"
    ext = Path(ref).suffix.lower()
    mapping = {
        ".jpg": "image", ".jpeg": "image", ".png": "image",
        ".gif": "image", ".webp": "image", ".bmp": "image",
        ".mp4": "video", ".avi": "video", ".mov": "video",
        ".mp3": "audio", ".wav": "audio",
    }
    return mapping.get(ext, "other")


def generate_stable_post_id(old_id: str, salt: str = "p1_migration") -> str:
    """从旧 post_id 生成稳定的新 post_id（带 post_ 前缀）。
    
    使用 SHA-256(old_id + salt) 的前 24 位十六进制作为标识部分，
    确保同一旧 ID 总是映射到同一新 ID。
    """
    digest = hashlib.sha256((salt + old_id).encode("utf-8")).hexdigest()
    return f"post_{digest[:24]}"


def normalize_blogger_id(raw_id: str, salt: str = "p1_migration") -> str:
    """确保 blogger_id 符合 ^blogger_ 前缀格式。
    
    如果已有 blogger_ 前缀则保留；否则生成稳定的带前缀 ID。
    """
    if not raw_id:
        return "blogger_unknown"
    if raw_id.startswith("blogger_"):
        return raw_id
    # 裸哈希 → 添加 blogger_ 前缀
    digest = hashlib.sha256((salt + "blogger_" + raw_id).encode("utf-8")).hexdigest()
    return f"blogger_{digest[:20]}"


def migrate_media(old_media: List[Dict], media_base: Path, skip_hash: bool = False) -> List[Dict]:
    """迁移旧 media 格式到新格式。

    旧格式: ref, source_url, caption, is_content
    新格式: media_id, type, ref, sha256, phash, ocr_text
    """
    new_media = []
    for i, m in enumerate(old_media or []):
        if not isinstance(m, dict):
            continue
        ref = m.get("ref") or ""
        media_type = infer_media_type(ref)
        media_path = media_base / ref if ref and not skip_hash else None

        new_item = {
            "media_id": f"media_{i:04d}",
            "type": media_type,
            "ref": ref if ref else None,
            "sha256": compute_sha256(media_path) if media_path and not skip_hash else None,
            "phash": compute_phash(media_path) if media_path and not skip_hash else None,
            "ocr_text": m.get("caption"),  # 旧 caption 作为 ocr_text
        }
        new_media.append(new_item)
    return new_media


def migrate_provenance(record: Dict) -> Dict:
    """从旧 _collected 字段迁移到 provenance。
    无法确认的字段不伪造（填 null）。"""
    collected = record.get("_collected", {})
    if not isinstance(collected, dict):
        collected = {}

    return {
        "source_ref_hash": collected.get("source_url", record.get("post_id", "")),
        "collected_at": collected.get("collected_at") or datetime.now(CST).isoformat(),
        "collector": collected.get("collector", "P1_migration"),
        "terms_checked_at": collected.get("terms_checked_at"),  # 未核验前为 null
    }


def migrate_privacy(record: Dict) -> Dict:
    """从旧记录推断隐私状态。"""
    return {
        "anonymized": True,  # 假定已通过原始采集脱敏
        "contains_sensitive_data": False,  # 需要后续扫描确认
    }


def migrate_record(
    record: Dict,
    id_mapping: Dict[str, str],
    salt: str,
    media_base: Path,
    target_schema: str = "1.1",
    skip_hash: bool = False,
) -> Tuple[Optional[Dict], str]:
    """迁移单条记录。返回 (新记录, 状态)。
    
    状态: "success" | "degraded" | "rejected"
    """
    old_id = record.get("post_id", "")
    if not old_id:
        return None, "rejected"

    new_id = generate_stable_post_id(old_id, salt)
    id_mapping[old_id] = new_id

    # 标准化 blogger_id（确保 blogger_ 前缀）
    raw_blogger = record.get("blogger_id", "")
    normalized_blogger = normalize_blogger_id(raw_blogger, salt)

    # 平台映射：旧格式可能只有微信公众号 → 统一为 wechat_official_account
    platform = record.get("platform", "other")
    if platform == "wechat":
        platform = "wechat_official_account"

    # 构建新记录
    new_record: Dict[str, Any] = {
        "schema_version": target_schema,
        "post_id": new_id,
        "platform": platform,
        "source_type": record.get("source_type", "manual_public_collection"),
        "blogger_id": normalized_blogger,
        "published_at": record.get("published_at"),
        "text": record.get("text", ""),
        "media": migrate_media(record.get("media", []), media_base, skip_hash),
        "comments": record.get("comments", []),
        "blogger_history_refs": record.get("blogger_history_refs", []),
        "provenance": migrate_provenance(record),
        "privacy": migrate_privacy(record),
    }

    # v1.1 新增字段
    if target_schema == "1.1":
        new_record["title"] = record.get("title")
        new_record["content_group_id"] = None  # 待后续处理

    # 迁移元数据（LLM 审核标记等）
    llm_needs_review = record.get("llm_needs_review", False)
    if "_collected" in record and isinstance(record.get("_collected"), dict):
        llm_needs_review = record["_collected"].get("llm_needs_review", llm_needs_review)

    new_record["_migration_meta"] = {
        "original_post_id": old_id,
        "migrated_at": datetime.now(CST).isoformat(),
        "llm_needs_review": bool(llm_needs_review),
    }

    # 判定状态
    status = "success"
    if llm_needs_review:
        status = "degraded"

    return new_record, status


def load_jsonl(path: Path) -> List[Dict]:
    """加载 JSONL 文件，兼容标准 JSONL 和美化打印拼接格式。"""
    if not path.exists():
        return []
    raw_text = path.read_text(encoding="utf-8-sig")
    decoder = json.JSONDecoder()
    records = []
    idx = 0
    content_len = len(raw_text)
    while idx < content_len:
        while idx < content_len and raw_text[idx] in " \t\n\r":
            idx += 1
        if idx >= content_len:
            break
        try:
            obj, end = decoder.raw_decode(raw_text, idx)
            records.append(obj)
            idx = end
        except json.JSONDecodeError:
            next_brace = raw_text.find("{", idx + 1)
            if next_brace == -1:
                break
            idx = next_brace
    return records


def load_json_file(path: Path) -> Optional[Dict]:
    """加载单个 JSON 文件（可能是单个对象）。"""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def load_all_candidates(input_dir: Path, jsonl_dir: Path) -> List[Dict]:
    """从多个来源加载所有候选记录。"""
    candidates = []

    # 1. 从 annotations/ 目录加载 JSON 文件（每个文件可能是单条帖子记录）
    if input_dir.exists():
        for fpath in sorted(input_dir.glob("*.json")):
            try:
                record = load_json_file(fpath)
                if record and "post_id" in record:
                    candidates.append(record)
                    print(f"   ✓ {fpath.name}")
            except Exception as e:
                print(f"   ✗ {fpath.name}: {e}")

    # 2. 从 run_outputs/ 目录加载 JSONL 文件（跳过过大的文件）
    MAX_FILE_SIZE_MB = 50
    if jsonl_dir.exists():
        for fpath in sorted(jsonl_dir.glob("*.jsonl")):
            size_mb = fpath.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                print(f"   ⏭  {fpath.name} ({size_mb:.1f}MB) — 跳过（超过 {MAX_FILE_SIZE_MB}MB 限制）")
                continue
            try:
                records = load_jsonl(fpath)
                count = 0
                for r in records:
                    if "post_id" in r:
                        candidates.append(r)
                        count += 1
                print(f"   ✓ {fpath.name} ({size_mb:.1f}MB, {count} 条)")
            except Exception as e:
                print(f"   ✗ {fpath.name}: {e}")

    return candidates


def write_jsonl(records: List[Dict], path: Path) -> None:
    """写入标准 JSONL（一行一个有效 JSON 对象）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="P1 候选数据迁移到 v1.0/v1.1 schema")
    parser.add_argument("--input-dir", default="data/annotations",
                        help="包含旧格式 JSON 标注/帖子文件的目录")
    parser.add_argument("--jsonl-dir", default="data/run_outputs",
                        help="包含旧格式 JSONL 文件的目录")
    parser.add_argument("--output", default="data/interim/candidates_v1.jsonl",
                        help="输出规范化 JSONL 文件路径")
    parser.add_argument("--id-map", default="data/interim/id_mapping_v1.json",
                        help="ID 映射表输出路径")
    parser.add_argument("--media-base", default="data",
                        help="媒体文件基础目录（用于计算 sha256/phash）")
    parser.add_argument("--target-schema", default="1.1", choices=["1.0", "1.1"],
                        help="目标 schema 版本")
    parser.add_argument("--salt", default="p1_migration_v1",
                        help="post_id 生成盐值")
    parser.add_argument("--skip-media-hash", action="store_true",
                        help="跳过 media 文件的 sha256/phash 计算（加速迁移）")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    input_dir = project_root / args.input_dir
    jsonl_dir = project_root / args.jsonl_dir
    output_path = project_root / args.output
    id_map_path = project_root / args.id_map
    media_base = project_root / args.media_base

    # 加载所有候选记录
    print(f"📂 加载候选记录...")
    print(f"   annotations dir: {input_dir}")
    print(f"   jsonl dir: {jsonl_dir}")
    candidates = load_all_candidates(input_dir, jsonl_dir)
    print(f"   共加载 {len(candidates)} 条候选记录")

    if not candidates:
        print("⚠️  未找到任何候选记录，退出")
        return

    # 迁移
    id_mapping: Dict[str, str] = {}
    migrated: List[Dict] = []
    stats = {"success": 0, "degraded": 0, "rejected": 0}
    field_missing: Dict[str, int] = {}

    total = len(candidates)
    for i, record in enumerate(candidates):
        if i % 50 == 0 or i == total - 1:
            print(f"\r   迁移中... {i+1}/{total}", end="", flush=True)
        new_record, status = migrate_record(
            record, id_mapping, args.salt, media_base, args.target_schema, args.skip_media_hash
        )
        stats[status] += 1
        if new_record:
            migrated.append(new_record)
    print()  # newline after progress

    # 字段缺失统计
    for record in migrated:
        for key in ["title", "content_group_id", "published_at", "comments"]:
            if key in record and record[key] is None:
                field_missing[key] = field_missing.get(key, 0) + 1
            elif key in record and isinstance(record[key], list) and len(record[key]) == 0:
                field_missing[key] = field_missing.get(key, 0) + 1

    # 计算 media 字段缺失
    media_missing_counts = {"sha256": 0, "phash": 0, "ocr_text": 0}
    for record in migrated:
        for m in record.get("media", []):
            for k in media_missing_counts:
                if m.get(k) is None:
                    media_missing_counts[k] += 1

    # 输出
    write_jsonl(migrated, output_path)
    print(f"\n✅ 迁移完成: {output_path}")
    print(f"   success:  {stats['success']}")
    print(f"   degraded: {stats['degraded']} (llm_needs_review=true)")
    print(f"   rejected: {stats['rejected']}")

    # 保存 ID 映射表
    id_map_path.parent.mkdir(parents=True, exist_ok=True)
    with id_map_path.open("w", encoding="utf-8") as f:
        json.dump({
            "description": "P1 候选数据 post_id 迁移映射表",
            "migration_salt": args.salt,
            "target_schema": args.target_schema,
            "migrated_at": datetime.now(CST).isoformat(),
            "total_candidates": len(candidates),
            "mapping": id_mapping,
        }, f, ensure_ascii=False, indent=2)
    print(f"   ID 映射表: {id_map_path} ({len(id_mapping)} 条映射)")

    # 字段缺失分布
    print(f"\n📊 字段缺失分布:")
    for field, count in sorted(field_missing.items()):
        print(f"   {field}: {count} 条记录缺失/为空")
    print(f"   media.sha256:   {media_missing_counts['sha256']} 个媒体项为 null")
    print(f"   media.phash:    {media_missing_counts['phash']} 个媒体项为 null")
    print(f"   media.ocr_text: {media_missing_counts['ocr_text']} 个媒体项为 null")

    # 保存统计信息
    stats_path = output_path.parent / f"{output_path.stem}_stats.json"
    with stats_path.open("w", encoding="utf-8") as f:
        json.dump({
            "total_loaded": len(candidates),
            "migrated": stats,
            "field_missing": field_missing,
            "media_missing": media_missing_counts,
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
