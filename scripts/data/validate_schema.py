#!/usr/bin/env python3
"""Schema 校验器 —— 读取权威 Schema 文件校验 JSONL 数据。

v1.1 改进：
  - 读取 data/schema/data_schema_v1_1.json（权威 schema），不维护另一套手写字段集合
  - 支持 --target-schema 指定校验版本（1.0 / 1.1）
  - 增加敏感字段扫描、高熵/密钥模式扫描、直接身份与 URL 参数脱敏检查
  - 支持 raw/interim/public 三层输出校验

用法：
  python scripts/data/validate_schema.py data/interim/candidates_v1.jsonl
  python scripts/data/validate_schema.py data/interim/candidates_v1.jsonl --target-schema 1.1 --privacy-scan
"""
import json
import re
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# ═══════════════════════════════════════════════════════════════
# Schema 加载
# ═══════════════════════════════════════════════════════════════

def load_authoritative_schema(project_root: Path, version: str = "1.1") -> Dict:
    """从权威 schema 文件加载 schema 定义。"""
    schema_map = {
        "1.0": "data/schema/data_schema_v1.json",
        "1.1": "data/schema/data_schema_v1_1.json",
    }
    schema_path = project_root / schema_map.get(version, schema_map["1.1"])
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_required_fields(schema: Dict) -> List[str]:
    """从 schema 定义中提取 content_record 的必填字段。"""
    content = schema.get("$defs", {}).get("content_record", {})
    return content.get("required", [])


def get_property_names(schema: Dict) -> List[str]:
    """从 schema 定义中提取 content_record 的所有属性名。"""
    content = schema.get("$defs", {}).get("content_record", {})
    return list(content.get("properties", {}).keys())


def get_platform_enum(schema: Dict) -> List[str]:
    """从 schema 中提取 platform 枚举值。"""
    content = schema.get("$defs", {}).get("content_record", {})
    platform_prop = content.get("properties", {}).get("platform", {})
    return platform_prop.get("enum", [])


# ═══════════════════════════════════════════════════════════════
# 敏感信息扫描
# ═══════════════════════════════════════════════════════════════

# 敏感字段模式
SENSITIVE_PATTERNS = [
    (r"\b1[3-9]\d{9}\b", "手机号"),
    (r"\b\d{3}[-.]?\d{4}[-.]?\d{4}\b", "固定电话"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "邮箱地址"),
    (r"\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b", "身份证号"),
    (r"\b(?:\d{3,4}-?){2,3}\d{3,4}\b", "疑似电话号码"),
    (r"\bhttps?://[^\s]*(\b(?:token|key|secret|password|auth|api_key|access_token)\b)[^\s]*", "含凭证的URL"),
]

# 高熵/密钥模式
HIGH_ENTROPY_PATTERNS = [
    (r"\b[A-Za-z0-9+/]{32,}={0,2}\b", "Base64 长字符串（疑似密钥）"),
    (r"\b[a-fA-F0-9]{32,64}\b", "十六进制长字符串（疑似哈希/密钥）"),
    (r"\b(?:sk-|pk-|AKIA)[A-Za-z0-9_\-+/]{20,}\b", "API 密钥模式"),
    (r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_\-+.=/]{20,}\b", "认证令牌"),
]

# 直接身份信息模式
PII_PATTERNS = [
    (r"(?:微信|WeChat)\s*(?:号|ID)?\s*[：:]\s*[A-Za-z0-9_-]{6,}", "微信号"),
    (r"(?:QQ|qq)\s*(?:号|号码)?\s*[：:]\s*\d{5,}", "QQ号"),
    (r"(?:地址|位置|地点)\s*[：:]\s*.{5,50}", "物理地址"),
]


def shannon_entropy(text: str) -> float:
    """计算文本的香农熵。"""
    if not text:
        return 0.0
    counter = Counter(text)
    length = len(text)
    entropy = 0.0
    for count in counter.values():
        prob = count / length
        entropy -= prob * math.log2(prob)
    return entropy


def scan_sensitive_content(record: Dict) -> List[Dict[str, str]]:
    """扫描记录中的敏感内容。返回发现列表。"""
    findings = []

    # 检查 text 字段
    text = record.get("text", "")
    if text:
        for pattern, label in SENSITIVE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                findings.append({
                    "field": "text",
                    "type": label,
                    "match": str(match)[:50],
                    "severity": "high",
                })

        for pattern, label in HIGH_ENTROPY_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                findings.append({
                    "field": "text",
                    "type": label,
                    "match": str(match)[:50],
                    "severity": "medium",
                })

        for pattern, label in PII_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                findings.append({
                    "field": "text",
                    "type": label,
                    "match": str(match)[:50],
                    "severity": "high",
                })

        # 高熵检测
        if len(text) > 20:
            entropy = shannon_entropy(text)
            if entropy > 5.5:
                findings.append({
                    "field": "text",
                    "type": "高熵文本（疑似编码/加密内容）",
                    "match": f"entropy={entropy:.2f}",
                    "severity": "low",
                })

    # 检查 media 中的 source_url（URL 参数可能含 PII）
    for i, m in enumerate(record.get("media", [])):
        if isinstance(m, dict):
            ref = m.get("ref", "") or ""
            for pattern, label in PII_PATTERNS:
                matches = re.findall(pattern, str(ref), re.IGNORECASE)
                for match in matches:
                    findings.append({
                        "field": f"media[{i}].ref",
                        "type": label,
                        "match": str(match)[:50],
                        "severity": "high",
                    })

    # 检查 title
    title = record.get("title", "") or ""
    if title:
        for pattern, label in SENSITIVE_PATTERNS:
            matches = re.findall(pattern, str(title), re.IGNORECASE)
            for match in matches:
                findings.append({
                    "field": "title",
                    "type": label,
                    "match": str(match)[:50],
                    "severity": "high",
                })

    return findings


# ═══════════════════════════════════════════════════════════════
# Schema 校验
# ═══════════════════════════════════════════════════════════════

def validate_record(record: Dict[str, Any], schema: Dict) -> List[str]:
    """根据权威 schema 校验单条记录。"""
    errors: List[str] = []
    pid = record.get("post_id", "?")

    required_fields = get_required_fields(schema)
    valid_platforms = get_platform_enum(schema)
    all_properties = get_property_names(schema)

    # 1. 必填字段存在性
    for field in required_fields:
        if field not in record:
            errors.append(f"missing required field: {field}")

    # 2. post_id 格式
    if "post_id" in record:
        if not re.match(r"^post_[A-Za-z0-9_-]+$", str(record["post_id"])):
            errors.append(f"post_id format invalid: {record['post_id']} (expected ^post_[A-Za-z0-9_-]+$)")

    # 3. platform 枚举校验
    if "platform" in record and valid_platforms:
        if record["platform"] not in valid_platforms:
            errors.append(f"platform '{record['platform']}' not in {valid_platforms}")

    # 4. blogger_id 格式
    if "blogger_id" in record:
        bid = str(record.get("blogger_id", ""))
        if not re.match(r"^blogger_[A-Za-z0-9_-]+$", bid):
            errors.append(f"blogger_id format invalid: {bid}")

    # 5. 类型校验
    if "media" in record and not isinstance(record["media"], list):
        errors.append("media must be a list")
    if "comments" in record and not isinstance(record["comments"], list):
        errors.append("comments must be a list")
    if "blogger_history_refs" in record and not isinstance(record["blogger_history_refs"], list):
        errors.append("blogger_history_refs must be a list")

    # 6. media 内部结构校验（v1.0/v1.1 格式）
    for i, m in enumerate(record.get("media", [])):
        if not isinstance(m, dict):
            errors.append(f"media[{i}] must be an object")
            continue
        for f in ("media_id", "type", "ref"):
            if f not in m:
                errors.append(f"media[{i}] missing {f}")

    # 7. provenance 内部结构
    provenance = record.get("provenance", {})
    if isinstance(provenance, dict):
        for f in ("source_ref_hash", "collected_at", "collector", "terms_checked_at"):
            if f not in provenance:
                errors.append(f"provenance missing {f}")

    # 8. privacy 内部结构
    privacy = record.get("privacy", {})
    if isinstance(privacy, dict):
        for f in ("anonymized", "contains_sensitive_data"):
            if f not in privacy:
                errors.append(f"privacy missing {f}")

    # 9. comments 内部结构（如有）
    for i, c in enumerate(record.get("comments", [])):
        if not isinstance(c, dict):
            errors.append(f"comments[{i}] must be an object")
            continue
        for f in ("comment_id", "author_id", "text", "like_count", "is_pinned"):
            if f not in c:
                errors.append(f"comments[{i}] missing {f}")

    # 10. schema_version 一致性
    schema_version = schema.get("$defs", {}).get("content_record", {}).get("properties", {}).get("schema_version", {}).get("const", "")
    if schema_version and record.get("schema_version") != schema_version:
        errors.append(f"schema_version mismatch: record={record.get('schema_version')}, expected={schema_version}")

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


def write_jsonl(records: Iterable[Dict], path: Path) -> None:
    """写入标准 JSONL（一行一个有效 JSON 对象）。"""
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(path: str, target_schema: str = "1.1", privacy_scan: bool = False,
         output_log: Optional[str] = None) -> int:
    project_root = Path(__file__).resolve().parent.parent.parent
    path_obj = Path(path)
    if not path_obj.is_absolute():
        path_obj = project_root / path

    if not path_obj.exists():
        print(f"ERROR: path does not exist: {path_obj}")
        return 1

    # 加载权威 schema
    schema = load_authoritative_schema(project_root, target_schema)
    print(f"📋 使用 schema: data_schema_v{target_schema}.json")

    total = 0
    invalid = 0
    warnings = 0
    privacy_findings_total = 0
    valid_records = []

    for record in load_jsonl(path_obj):
        total += 1
        errors = validate_record(record, schema)

        # 隐私扫描
        privacy_findings = []
        if privacy_scan:
            privacy_findings = scan_sensitive_content(record)
            if privacy_findings:
                privacy_findings_total += len(privacy_findings)

        if errors or privacy_findings:
            if errors:
                invalid += 1
                print(f"\n[{record.get('post_id', 'unknown')}] ❌ errors:")
                for error in errors:
                    print(f"  - {error}")
            if privacy_findings:
                print(f"  🔒 隐私警告:")
                for pf in privacy_findings:
                    print(f"    [{pf['severity']}] {pf['field']}: {pf['type']} ({pf['match']})")
        else:
            valid_records.append(record)

    # 摘要
    print(f"\n{'='*60}")
    print(f"📊 校验完成: {path_obj.name}")
    print(f"   总记录:   {total}")
    print(f"   有效:     {total - invalid}")
    print(f"   无效:     {invalid}")
    if privacy_scan:
        print(f"   隐私告警: {privacy_findings_total}")
    print(f"{'='*60}")

    # 保存校验日志
    if output_log:
        log_path = Path(output_log)
        if not log_path.is_absolute():
            log_path = project_root / output_log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as f:
            json.dump({
                "validated_at": __import__("datetime").datetime.now().isoformat(),
                "schema_version": target_schema,
                "total": total,
                "valid": total - invalid,
                "invalid": invalid,
                "privacy_findings": privacy_findings_total if privacy_scan else "disabled",
            }, f, ensure_ascii=False, indent=2)
        print(f"📝 校验日志: {log_path}")

    return 0 if invalid == 0 else 2


if __name__ == "__main__":
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="Schema 校验器（读取权威 schema）")
    parser.add_argument("input", nargs="?", default="data/interim/candidates_v1.jsonl",
                        help="待校验的 JSONL 文件路径")
    parser.add_argument("--target-schema", default="1.1", choices=["1.0", "1.1"],
                        help="目标 schema 版本")
    parser.add_argument("--privacy-scan", action="store_true",
                        help="启用敏感信息扫描")
    parser.add_argument("--output-log", default=None,
                        help="校验日志输出路径")
    args = parser.parse_args()
    sys.exit(main(args.input, args.target_schema, args.privacy_scan, args.output_log))
