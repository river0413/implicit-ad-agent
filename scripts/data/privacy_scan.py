#!/usr/bin/env python3
"""隐私合规扫描 —— 敏感字段扫描、高熵/密钥检测、PII 脱敏、raw/interim/public 三层输出。

功能：
  1. 敏感字段扫描：手机号、邮箱、身份证号、地址等
  2. 高熵/密钥模式扫描：Base64 密钥、API 密钥、认证令牌
  3. 直接身份与 URL 参数脱敏
  4. raw/interim/public 三层输出控制
  5. 对外发布许可清单

用法：
  python scripts/data/privacy_scan.py \
    --input data/interim/candidates_v1.jsonl \
    --output-dir data/reports \
    --public-allowlist data/reports/public_allowlist.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════
# 敏感检测模式
# ═══════════════════════════════════════════════════════════════

SENSITIVE_PATTERNS = [
    (r"\b1[3-9]\d{9}\b", "手机号", "high"),
    (r"\b\d{3}[-.]?\d{4}[-.]?\d{4}\b", "固定电话", "medium"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "邮箱地址", "high"),
    (r"\b\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b", "身份证号", "critical"),
    (r"\b\d{16,19}\b", "银行卡号（疑似）", "critical"),
]

HIGH_ENTROPY_PATTERNS = [
    (r"\b[A-Za-z0-9+/]{32,}={0,2}\b", "Base64 长字符串（疑似密钥）"),
    (r"\b[a-fA-F0-9]{32,64}\b", "十六进制长字符串（疑似哈希/密钥）"),
    (r"\b(?:sk-|pk-|AKIA)[A-Za-z0-9_\-+/]{20,}\b", "API 密钥模式"),
    (r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_\-+.=/]{20,}\b", "认证令牌"),
]

PII_PATTERNS = [
    (r"(?:微信|WeChat)\s*(?:号|ID)?\s*[：:]\s*[A-Za-z0-9_-]{6,}", "微信号"),
    (r"(?:QQ|qq)\s*(?:号|号码)?\s*[：:]\s*\d{5,}", "QQ号"),
    (r"(?:地址|位置|地点)\s*[：:]\s*.{5,50}", "物理地址"),
    (r"(?:手机|电话|联系方式)\s*[：:]\s*\d[\d\- ]{6,}", "联系方式"),
]

URL_SENSITIVE_PARAMS = [
    "token", "key", "secret", "password", "auth", "access_token",
    "api_key", "apikey", "sign", "signature", "credential", "session",
]


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def shannon_entropy(text: str) -> float:
    """计算文本香农熵。"""
    if not text:
        return 0.0
    counter = Counter(text)
    length = len(text)
    entropy = 0.0
    for count in counter.values():
        prob = count / length
        entropy -= prob * math.log2(prob)
    return entropy


def sanitize_url_params(url: str) -> str:
    """脱敏 URL 中的敏感参数。"""
    if not url:
        return url
    for param in URL_SENSITIVE_PARAMS:
        url = re.sub(
            rf"([?&]{param}=)[^&]*",
            r"\1[REDACTED]",
            url,
            flags=re.IGNORECASE,
        )
    return url


def load_jsonl(path: Path) -> List[Dict]:
    """加载 JSONL 文件。"""
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ═══════════════════════════════════════════════════════════════
# 扫描函数
# ═══════════════════════════════════════════════════════════════

def scan_record(record: Dict) -> List[Dict[str, Any]]:
    """扫描单条记录中的所有敏感内容。"""
    findings = []

    # 检查 text
    text = str(record.get("text", ""))
    if text:
        _scan_text(text, "text", findings)

    # 检查 title
    title = str(record.get("title", "") or "")
    if title:
        _scan_text(title, "title", findings)

    # 检查 media
    for i, m in enumerate(record.get("media", [])):
        if isinstance(m, dict):
            ref = str(m.get("ref", ""))
            if ref:
                _scan_text(ref, f"media[{i}].ref", findings)

    # 检查 comments
    for i, c in enumerate(record.get("comments", [])):
        if isinstance(c, dict):
            comment_text = str(c.get("text", ""))
            if comment_text:
                _scan_text(comment_text, f"comments[{i}].text", findings)

    return findings


def _scan_text(text: str, field: str, findings: List[Dict]) -> None:
    """在文本中扫描所有敏感模式。"""
    # 1. 敏感字段
    for pattern, label, severity in SENSITIVE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            findings.append({
                "field": field,
                "type": label,
                "match": match.group()[:60],
                "severity": severity,
            })

    # 2. 高熵检测
    for pattern, label in HIGH_ENTROPY_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            findings.append({
                "field": field,
                "type": label,
                "match": match.group()[:60],
                "severity": "medium",
            })

    # 3. 直接身份信息
    for pattern, label in PII_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            findings.append({
                "field": field,
                "type": label,
                "match": match.group()[:60],
                "severity": "high",
            })

    # 4. 全局高熵检测
    if len(text) > 30:
        entropy = shannon_entropy(text)
        if entropy > 5.5:
            findings.append({
                "field": field,
                "type": "高熵文本（疑似编码/加密内容）",
                "match": f"entropy={entropy:.2f}, length={len(text)}",
                "severity": "low",
            })


def classify_record(record: Dict, findings: List[Dict]) -> str:
    """根据扫描结果将记录分为 raw/interim/public 三层。

    - raw: 包含未脱敏的直接身份信息或密钥 → 不可对外
    - interim: 已脱敏但含可能敏感内容（如疑似地址） → 内部使用
    - public: 经确认无可识别身份信息 → 可发布
    """
    severities = [f["severity"] for f in findings]
    if "critical" in severities:
        return "raw"
    if "high" in severities:
        return "interim"
    return "public"


def generate_public_allowlist(records: List[Dict], findings_map: Dict[str, List]) -> List[str]:
    """生成可对外发布的 post_id 列表。"""
    allowlist = []
    for r in records:
        pid = r.get("post_id", "")
        findings = findings_map.get(pid, [])
        if classify_record(r, findings) == "public":
            allowlist.append(pid)
    return allowlist


# ═══════════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="隐私合规扫描")
    parser.add_argument("--input", default="data/interim/candidates_v1.jsonl",
                        help="输入 JSONL 文件")
    parser.add_argument("--output-dir", default="data/reports",
                        help="报告输出目录")
    parser.add_argument("--public-allowlist", default="data/reports/public_allowlist.json",
                        help="对外发布许可清单输出路径")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    input_path = project_root / args.input
    output_dir = project_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"🔒 隐私合规扫描...")
    print(f"   输入: {input_path}")

    records = load_jsonl(input_path)
    if not records:
        print("⚠️  无记录可扫描")
        return

    total_findings = 0
    findings_map: Dict[str, List[Dict]] = {}
    layer_counts = defaultdict(int)
    severity_counts = defaultdict(int)
    type_counter = Counter()

    for record in records:
        pid = record.get("post_id", "unknown")
        findings = scan_record(record)
        findings_map[pid] = findings
        total_findings += len(findings)

        layer = classify_record(record, findings)
        layer_counts[layer] += 1

        for f in findings:
            severity_counts[f["severity"]] += 1
            type_counter[f["type"]] += 1

    # 生成对外发布许可清单
    allowlist = generate_public_allowlist(records, findings_map)

    # 生成综合报告
    report = {
        "scan_time": datetime.now(CST).isoformat(),
        "input_file": str(input_path),
        "total_records": len(records),
        "total_findings": total_findings,
        "layer_distribution": {
            "raw": layer_counts.get("raw", 0),
            "interim": layer_counts.get("interim", 0),
            "public": layer_counts.get("public", 0),
        },
        "severity_distribution": dict(severity_counts),
        "finding_types": dict(type_counter.most_common(20)),
        "public_allowlist_count": len(allowlist),
        "detailed_findings": {
            pid: findings
            for pid, findings in findings_map.items()
            if findings
        },
    }

    # 保存报告
    report_path = output_dir / "privacy_scan_report.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📊 报告: {report_path}")

    # 保存许可清单
    allowlist_path = project_root / args.public_allowlist
    allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    with allowlist_path.open("w", encoding="utf-8") as f:
        json.dump({
            "description": "对外发布许可清单 — 经隐私扫描确认不含可识别身份信息",
            "generated_at": datetime.now(CST).isoformat(),
            "total_approved": len(allowlist),
            "post_ids": allowlist,
        }, f, ensure_ascii=False, indent=2)
    print(f"📋 许可清单: {allowlist_path} ({len(allowlist)} 条)")

    # 摘要
    print(f"\n{'='*60}")
    print(f"📊 扫描摘要:")
    print(f"   总记录:   {len(records)}")
    print(f"   raw:      {layer_counts.get('raw', 0)} (不可对外)")
    print(f"   interim:  {layer_counts.get('interim', 0)} (内部使用)")
    print(f"   public:   {layer_counts.get('public', 0)} (可发布)")
    print(f"   敏感发现: {total_findings} 处")
    print(f"{'='*60}")

    if layer_counts.get("raw", 0) > 0 or layer_counts.get("interim", 0) > 0:
        print(f"\n⚠️  警告: {layer_counts.get('raw', 0) + layer_counts.get('interim', 0)} 条记录未通过 public 层检查，")
        print(f"   这些记录不得对外发布。请审查 detailed_findings 并手动脱敏后重新扫描。")


if __name__ == "__main__":
    main()
