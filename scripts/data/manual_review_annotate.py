#!/usr/bin/env python3
"""手动复核标注程序 —— 交互式 CLI，LLM 辅助预判 + 人工确认/修正。

功能：
  1. 加载 JSONL 帖子数据 + 标注指南
  2. 请求标注人 ID，按 ID + 时间分文件保存
  3. 同一标注人断点续传：检测已有标注文件，跳过已完成 post_id
  4. 每条帖子展示标题/正文/媒体引用 → 可选查看图片 → LLM 预分析 → 人工确认/修改/跳过
  5. 逐条即时写入 JSON（缩进易读格式），崩溃不丢数据
  6. 输出合并格式：主标注字段（label/evidence) + 补充 Schema 字段
     （image_analyses/markdown_notes/edge_case_discussion），
     可通过 --no-supplement 仅输出主标注字段
  7. 支持查看图片：[v] 交互式选择编号打开，--auto-view 自动弹出

用法：
  python scripts/data/manual_review_annotate.py \\
    --input data/run_outputs/anonymized_posts.jsonl \\
    --guide docs/annotation_guide.md \\
    --output-dir data/annotations \\
    --media-base data \\
    --limit 50

依赖：pip install openai python-dotenv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ── 项目根目录加入 sys.path ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CST = timezone(timedelta(hours=8))  # 中国标准时间 +08:00

# ── 标签与证据代码 ──
VALID_LABELS = {"明广", "暗广", "非广", "out_of_scope"}
EVIDENCE_CODES = {
    "D": "明示商业关系（广告/赞助/合作标识）",
    "C": "明确商业对象（单一品牌/商品/店铺/服务为核心）",
    "P": "劝服/促销话术（极端夸赞、限时限量、价格刺激、稀缺焦虑）",
    "A": "转化动作（下单、扫码、优惠码、评论区取链接）",
    "V": "视觉商业证据（产品特写、Logo大图、价格表、销量图）",
    "B": "行为偏移（与博主既往人设/主题明显不符）",
    "M": "评论异常（置顶导流、格式化赞美、重复模板评论）",
}

# ── 标注指南摘要（嵌入版本，正式以 docs/annotation_guide.md 为准） ──
ANNOTATION_GUIDE_SUMMARY = """\
═══════════════════════════════════════════════════════════════
                    标注指南 v1.0 速查
═══════════════════════════════════════════════════════════════

【三元标签】明广 / 暗广 / 非广 / out_of_scope

【判定流程】
  Step 1 → 是否在研究范围内？否 → out_of_scope
  Step 2 → 是否有 D（明示商业关系标识）且内容为推广？是 → 明广
  Step 3 → 是否有 C（明确商业对象）？否 → 非广（大概率）
  Step 4 → C 存在时：是否有 P/A/V/B/M 中 ≥2 条独立证据？
            或是否有 A（直接转化动作）？
            是 → 暗广  否 → 非广
  Step 5 → 证据不足/无法确定 → 进入人工复核

【优先级】明确披露 > 直接转化 > 多源证据组合 > 主观语气
  单独出现"好用""推荐"不足以认定暗广。

【关键边界案例】
  - 有"广告"标签 + 推荐品牌 → 明广
  - 无标识 + 专属优惠码/购买链接 → 暗广
  - 纯知识科普，提产品但无推荐语无链接 → 非广
  - 产品测评列优缺点，说"理性消费" → 非广
  - 博主置顶评论"加V购买同款"，正文未提品牌 → 暗广或复核
  - 声称"自费购入"同时给专属优惠码 → 暗广（自述不能抵消A）
═══════════════════════════════════════════════════════════════"""


# ── LLM 预分析 Prompt ──
LLM_PRE_ANALYSIS_SYSTEM = """你是一个社交媒体内容审核专家，专门识别"隐性广告（暗广）"。
你的任务是对给定的帖子进行预分析，依据标注规范给出初步判断。

## 标注规范要点

**三元标签**：明广 / 暗广 / 非广 / out_of_scope

**证据编码**：
- D: 明示商业关系（广告/赞助/合作标识）
- C: 明确商业对象（全文围绕单一品牌/商品/店铺/服务展开）
- P: 劝服/促销话术（极端夸赞、限时限量、价格刺激、制造稀缺焦虑）
- A: 转化动作（引导下单、扫码跳转、专属优惠码、"评论区取链接"）
- V: 视觉商业证据（产品特写、Logo大图、价格表/优惠券截图、销量数据图表）
- B: 行为偏移（与博主既往人设/主题明显不符）
- M: 评论异常（置顶购买链接、格式雷同赞美、统一"已买""求链接"队形）

**判定逻辑**：
1. 先判是否在研究范围内（非商业内容、纯个人二手交易、公益宣传 → out_of_scope）
2. 有 D 且内容为推广 → 明广
3. 无 D 也无 C → 非广
4. 有 C 且 (P/A/V/B/M 中 ≥2条 或 有 A) → 暗广
5. 证据不足 → 非广；无法确定 → 需复核

**重要**：单独出现"好用""推荐""必备"等词不足以认定暗广。"自费购买"声明不能抵消直接转化证据（A）。

请以 JSON 格式返回分析结果，字段如下：
- label: 明广/暗广/非广/out_of_scope
- confidence: 0.0~1.0 的确信度
- evidence_codes: 证据代码列表，如 ["C","P","A"]
- evidence: 逐条具体证据描述（从帖子中引用原文或描述观察）
- reasoning: 判定推理过程（1-3句话）
- uncertain_reason: 如果不确定，说明原因；否则填 null

只返回 JSON，不要有其他文字。"""


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """加载 JSONL 文件，返回记录列表。

    兼容两种格式：
      - 标准 JSONL（每行一个完整 JSON 对象）
      - 美化打印的 JSONL（每个对象跨多行，以缩进格式存储）
    """
    raw_text = path.read_text(encoding="utf-8")
    # 尝试标准 JSONL 逐行解析
    records = []
    decoder = json.JSONDecoder()
    idx = 0
    raw_text = raw_text.strip()
    while idx < len(raw_text):
        # 跳过空白
        while idx < len(raw_text) and raw_text[idx] in " \t\n\r":
            idx += 1
        if idx >= len(raw_text):
            break
        try:
            obj, end = decoder.raw_decode(raw_text, idx)
            records.append(obj)
            idx = end
        except json.JSONDecodeError:
            # 如果流式解析失败，尝试逐行解析作为后备
            records = _load_standard_jsonl(path)
            break
    return records


def _load_standard_jsonl(path: Path) -> List[Dict[str, Any]]:
    """标准 JSONL 逐行解析（后备方案）。"""
    records = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def load_guide(path: Path) -> str:
    """加载标注指南全文。"""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ANNOTATION_GUIDE_SUMMARY


def find_existing_annotations(output_dir: Path, annotator_id: str) -> Tuple[Optional[Path], Set[str]]:
    """查找该标注人的已有标注文件及已完成 post_id 集合。

    兼容旧版 .jsonl（单行 JSON）和新版 .json（缩进多行 JSON）。

    Returns:
        (latest_file_path, set_of_completed_post_ids)
        若不存在则返回 (None, empty_set)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # 同时搜索 .json 和 .jsonl 以兼容旧文件
    candidates = list(output_dir.glob(f"{annotator_id}_*.json"))
    candidates += list(output_dir.glob(f"{annotator_id}_*.jsonl"))
    if not candidates:
        return None, set()
    existing = sorted(candidates, key=os.path.getmtime, reverse=True)

    latest = existing[0]
    completed: Set[str] = set()
    raw_text = latest.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(raw_text):
        while idx < len(raw_text) and raw_text[idx] in " \t\n\r":
            idx += 1
        if idx >= len(raw_text):
            break
        try:
            obj, end = decoder.raw_decode(raw_text, idx)
            completed.add(obj.get("post_id", ""))
            idx = end
        except json.JSONDecodeError:
            break
    return latest, completed


def call_llm_pre_analysis(
    post: Dict[str, Any],
    guide_text: str,
) -> Dict[str, Any]:
    """调用 LLM 对单条帖子进行预分析。"""
    from openai import OpenAI
    from dotenv import load_dotenv

    load_dotenv()

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    title = post.get("title") or ""
    text = post.get("text", "")
    # 截断过长的正文（保留前 5000 字）
    if len(text) > 5000:
        text = text[:5000] + "\n\n[... 正文过长已截断，完整内容请查看原始数据 ...]"

    media_count = len(post.get("media", []))
    comment_count = len(post.get("comments", []))
    history_count = len(post.get("blogger_history_refs", []))

    user_prompt = f"""请分析以下社交媒体帖子，判断其是否为隐性广告。

---
【标题】{title}

【正文】
{text}

【媒体】共 {media_count} 张图片
【评论】共 {comment_count} 条
【博主历史文章数】{history_count} 篇
---

请依据标注规范，返回 JSON 格式的分析结果。"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": LLM_PRE_ANALYSIS_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        # 清理可能的 markdown 代码块包裹
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        result = json.loads(content)
    except Exception as e:
        result = {
            "label": "非广",
            "confidence": 0.3,
            "evidence_codes": [],
            "evidence": [],
            "reasoning": f"LLM 调用失败: {e}",
            "uncertain_reason": "LLM 分析不可用，需人工独立判断",
        }

    # 标准化字段
    result.setdefault("label", "非广")
    result.setdefault("confidence", 0.5)
    result.setdefault("evidence_codes", [])
    result.setdefault("evidence", [])
    result.setdefault("reasoning", "")
    result.setdefault("uncertain_reason", None)

    # 校验 label
    if result["label"] not in VALID_LABELS:
        result["label"] = "非广"

    # 校验 evidence_codes
    result["evidence_codes"] = [
        c for c in result["evidence_codes"] if c in EVIDENCE_CODES
    ]

    return result


def format_post_display(post: Dict[str, Any], index: int, total: int) -> str:
    """格式化帖子展示文本。"""
    title = post.get("title") or "(无标题)"
    text = post.get("text", "")
    if len(text) > 800:
        text = text[:800] + "\n\n[... 正文过长已截断，完整内容请查看原始数据 ...]"

    media_count = len(post.get("media", []))
    media_refs = ""
    if media_count > 0:
        refs = [m.get("ref", "?") for m in post["media"][:5]]
        media_refs = f"\n  📷 图片({media_count}张): " + ", ".join(refs)
        if media_count > 5:
            media_refs += f" ... 等共{media_count}张"

    comment_count = len(post.get("comments", []))
    blog_id = post.get("blogger_id", "?")
    platform = post.get("platform", "?")
    published = post.get("published_at") or "未知"

    return f"""\
{'─' * 70}
📌 [{index}/{total}]  {title}
{'─' * 70}
🆔 post_id: {post.get('post_id', '?')}
📅 发布时间: {published}
📱 平台: {platform}  |  博主: {blog_id[:16]}...{media_refs}
💬 评论数: {comment_count}
{'─' * 70}
📝 正文:
{text}
{'─' * 70}"""


def view_images(post: Dict[str, Any], media_base: Path) -> int:
    """打开帖子的图片供查看，返回实际打开的图片数。

    使用系统默认图片查看器打开，Windows 下调用 os.startfile，
    其他平台使用 webbrowser.open。
    支持批量打开（传入索引范围如 1-5）或逐张打开。
    """
    media = post.get("media", [])
    if not media:
        print("  (无图片)")
        return 0

    print(f"\n📷 共 {len(media)} 张图片:")
    for i, m in enumerate(media, 1):
        ref = m.get("ref", "?")
        full_path = media_base / ref
        exists = "✓" if full_path.exists() else "✗ 缺失"
        print(f"  [{i}] {ref}  {exists}")

    print("\n  输入编号打开（如 1,3,5 或 1-3），直接回车跳过，a=全部打开")
    choice = input("  > ").strip().lower()

    if not choice:
        return 0

    # 解析选择
    indices: List[int] = []
    if choice == "a":
        indices = list(range(1, len(media) + 1))
    else:
        for part in choice.replace("，", ",").split(","):
            part = part.strip()
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    indices.extend(range(int(a), int(b) + 1))
                except ValueError:
                    continue
            elif part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(media):
                    indices.append(idx)

    if not indices:
        return 0

    # 去重排序
    indices = sorted(set(indices))
    opened = 0
    for idx in indices:
        ref = media[idx - 1].get("ref", "")
        full_path = media_base / ref
        if not full_path.exists():
            print(f"  ⚠️ [{idx}] 文件不存在: {full_path}")
            continue
        try:
            _open_file(str(full_path.resolve()))
            opened += 1
        except Exception as e:
            print(f"  ⚠️ [{idx}] 打开失败: {e}")

    print(f"  ✅ 已打开 {opened} 张图片")
    return opened


def _open_file(path: str) -> None:
    """跨平台打开文件。"""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", path], check=True)
    else:
        import webbrowser
        webbrowser.open(f"file://{path}")


def format_llm_suggestion(llm_result: Dict[str, Any]) -> str:
    """格式化 LLM 预分析建议。"""
    label = llm_result.get("label", "?")
    confidence = llm_result.get("confidence", 0)
    confidence_bar = "█" * int(confidence * 10) + "░" * (10 - int(confidence * 10))
    evidence_codes = ", ".join(llm_result.get("evidence_codes", [])) or "(无)"
    reasoning = llm_result.get("reasoning", "")
    evidence = llm_result.get("evidence", [])
    uncertain = llm_result.get("uncertain_reason")

    lines = [
        "",
        "🤖 ────── LLM 预分析建议 ──────",
        f"   标签: {label}  确信度: {confidence_bar} {confidence:.0%}",
        f"   证据代码: {evidence_codes}",
        f"   推理: {reasoning}",
    ]
    if len(evidence) == 1:
        lines.append(f"   具体证据: {evidence[0]}")
    elif len(evidence) > 1:
        lines.append("   具体证据:")
        for i, ev in enumerate(evidence, 1):
            lines.append(f"     {i}. {ev}")
    if uncertain:
        lines.append(f"   ⚠️ 不确定原因: {uncertain}")
    lines.append("🤖 ──────────────────────────────\n")
    return "\n".join(lines)


def prompt_label_choice(llm_label: str) -> str:
    """交互式选择标签。"""
    print("\n请选择最终标签：")
    options = list(VALID_LABELS)
    default_idx = options.index(llm_label) if llm_label in options else 2  # 默认"非广"

    for i, opt in enumerate(options):
        marker = " ← 默认" if i == default_idx else ""
        print(f"  [{i}] {opt}{marker}")

    while True:
        choice = input(f"输入编号 (0-{len(options)-1}) 或直接回车使用默认值: ").strip()
        if choice == "":
            return options[default_idx]
        if choice.isdigit() and 0 <= int(choice) < len(options):
            return options[int(choice)]
        print(f"  无效输入，请输入 0-{len(options)-1}")


def prompt_evidence_codes() -> List[str]:
    """交互式选择证据代码。"""
    print("\n证据代码（可多选，用逗号分隔，如 C,P,A）：")
    codes = list(EVIDENCE_CODES.keys())
    for i, code in enumerate(codes):
        print(f"  [{code}] {EVIDENCE_CODES[code]}")
    print("  直接回车 = 不选任何证据代码")

    while True:
        choice = input("输入证据代码: ").strip().upper()
        if choice == "":
            return []
        selected = [c.strip() for c in choice.replace("，", ",").split(",") if c.strip()]
        invalid = [c for c in selected if c not in EVIDENCE_CODES]
        if invalid:
            print(f"  无效代码: {invalid}，请重新输入")
            continue
        return selected


def prompt_confidence() -> float:
    """交互式输入确信度。"""
    while True:
        val = input("确信度 (0.0~1.0，直接回车=0.8): ").strip()
        if val == "":
            return 0.8
        try:
            v = float(val)
            if 0.0 <= v <= 1.0:
                return v
            print("  请输入 0.0 ~ 1.0 之间的数字")
        except ValueError:
            print("  请输入有效数字")


def prompt_evidence_text() -> List[str]:
    """交互式输入证据文本。"""
    print("逐条输入证据文本（空行结束）：")
    items = []
    i = 1
    while True:
        line = input(f"  证据{i}: ").strip()
        if line == "":
            break
        items.append(line)
        i += 1
    return items


def make_annotation_record(
    post_id: str,
    annotator_id: str,
    label: str,
    confidence: float,
    evidence_codes: List[str],
    evidence: List[str],
    uncertain_reason: Optional[str] = None,
    llm_suggestion: Optional[Dict[str, Any]] = None,
    image_analyses: Optional[List[Dict[str, Any]]] = None,
    markdown_notes: str = "",
    edge_case_discussion: Optional[Dict[str, Any]] = None,
    post: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造合并格式的标注记录：帖子原文 + 主标注字段 + 补充 Schema 字段。"""
    now_iso = datetime.now(CST).isoformat()
    record: Dict[str, Any] = {
        # ── 帖子原文（只读引用，便于自包含查阅） ──
        "post": post or {},
        # ── 主标注字段 (annotation_guide.md) ──
        "post_id": post_id,
        "annotator_id": annotator_id,
        "guide_version": "1.0",
        "label": label,
        "confidence": confidence,
        "evidence_codes": evidence_codes,
        "evidence": evidence,
        "uncertain_reason": uncertain_reason,
        # ── 补充 Schema 字段 (annotation_supplement_schema.md) ──
        "image_analyses": image_analyses or [],
        "markdown_notes": markdown_notes,
        "edge_case_discussion": edge_case_discussion,
        # ── 时间戳 ──
        "annotated_at": now_iso,
    }
    if llm_suggestion:
        record["_llm_suggestion"] = {
            "label": llm_suggestion.get("label"),
            "confidence": llm_suggestion.get("confidence"),
            "evidence_codes": llm_suggestion.get("evidence_codes", []),
            "reasoning": llm_suggestion.get("reasoning", ""),
        }
    return record


def prompt_image_analysis(post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """交互式填写图像分析（可选）。"""
    media = post.get("media", [])
    if not media:
        return []
    print(f"\n📷 该帖子有 {len(media)} 张图片，是否逐张分析？")
    resp = input("  输入要分析的图片编号（如 1,3,5，逗号分隔），直接回车跳过: ").strip()
    if not resp:
        return []

    indices = []
    for part in resp.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(media):
                indices.append(idx)

    if not indices:
        return []

    results = []
    for img_idx in indices:
        m = media[img_idx - 1]
        ref = m.get("ref", "?")
        url = m.get("source_url", "")
        print(f"\n  ── 图片 {img_idx}: {ref} ──")

        desc = input(f"  图片描述（1-2句话）: ").strip()
        if not desc:
            continue

        ocr = input(f"  OCR/图中文字（直接回车跳过）: ").strip() or None

        print(f"  视觉元素检测（y=是，其他=否）:")
        elements = {
            "has_logo": input(f"    品牌Logo? [y/N]: ").strip().lower() == "y",
            "has_qr_code": input(f"    二维码? [y/N]: ").strip().lower() == "y",
            "has_price_info": input(f"    价格/折扣信息? [y/N]: ").strip().lower() == "y",
            "has_product_image": input(f"    产品特写/白底商品图? [y/N]: ").strip().lower() == "y",
            "has_chart_or_table": input(f"    销量图表/对比表格? [y/N]: ").strip().lower() == "y",
            "has_promotional_text": input(f"    图片内促销文案? [y/N]: ").strip().lower() == "y",
            "has_contact_info": input(f"    联系方式(微信号/手机等)? [y/N]: ").strip().lower() == "y",
        }

        codes_input = input(f"  证据代码（V/A/D，逗号分隔，直接回车=无）: ").strip().upper()
        vcodes = []
        if codes_input:
            vcodes = [c.strip() for c in codes_input.replace("，", ",").split(",") if c.strip() in ("V", "A", "D")]

        relevance = input(f"  对标注判定的影响: ").strip()
        quality = input(f"  图片质量（直接回车=清晰）: ").strip() or "清晰"

        results.append({
            "media_ref": ref,
            "source_url": url or None,
            "image_index": img_idx,
            "analysis_method": "manual",
            "description": desc,
            "ocr_text": ocr,
            "detected_elements": elements,
            "visual_evidence_codes": vcodes,
            "relevance_to_annotation": relevance or "待补充",
            "image_quality_notes": quality,
            "analyzed_at": datetime.now(CST).isoformat(),
        })

    return results


def prompt_markdown_notes() -> str:
    """交互式输入 Markdown 备注（可选）。"""
    print("\n📝 Markdown 备注（判定思考/证据补充/疑虑，空行结束）:")
    lines = []
    while True:
        line = input("  | ").rstrip()
        if line == "" and (not lines or lines[-1] == ""):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def prompt_edge_case() -> Optional[Dict[str, Any]]:
    """交互式填写边界案例讨论（可选）。"""
    resp = input("\n⚠️  是否标记为边界案例？[y/N]: ").strip().lower()
    if resp != "y":
        return None

    category = input("  边界类型标签: ").strip()
    diff = input("  难度 [easy/medium/hard，默认medium]: ").strip() or "medium"
    alt = input("  另一种可能标签 [明广/暗广/非广/out_of_scope]: ").strip()
    reason = input("  不确定原因: ").strip()
    suggestion = input("  规范修订建议（直接回车跳过）: ").strip() or None
    need_disc = input("  需要团队讨论？[y/N]: ").strip().lower() == "y"
    tags_input = input("  讨论标签（逗号分隔）: ").strip()
    tags = [t.strip() for t in tags_input.replace("，", ",").split(",") if t.strip()] if tags_input else []

    return {
        "is_edge_case": True,
        "edge_case_category": category or None,
        "difficulty": diff if diff in ("easy", "medium", "hard") else "medium",
        "alternative_label": alt if alt in ("明广", "暗广", "非广", "out_of_scope") else None,
        "reason_for_uncertainty": reason or None,
        "suggested_guide_update": suggestion,
        "needs_team_discussion": need_disc,
        "discussion_tags": tags,
    }


def append_annotation(file_path: Path, record: Dict[str, Any]) -> None:
    """追加一条标注到 JSON 文件（缩进易读格式）。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n\n")


def print_stats(records: List[Dict[str, Any]]) -> None:
    """打印标注统计。"""
    from collections import Counter
    labels = Counter(r["label"] for r in records)
    total = len(records)
    print(f"\n{'=' * 50}")
    print(f"  本次标注统计: 共 {total} 条")
    for label in ["明广", "暗广", "非广", "out_of_scope"]:
        count = labels.get(label, 0)
        pct = count / total * 100 if total else 0
        print(f"    {label}: {count} ({pct:.1f}%)")
    print(f"{'=' * 50}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="手动复核标注程序 —— LLM 辅助预判 + 人工确认",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              # 从头开始标注（限制 20 条）
              python scripts/data/manual_review_annotate.py --limit 20

              # 指定输入输出
              python scripts/data/manual_review_annotate.py \\
                --input data/run_outputs/anonymized_posts.jsonl \\
                --output-dir data/annotations

              # 断点续传（自动检测已有标注文件）
              python scripts/data/manual_review_annotate.py --limit 100
        """),
    )
    parser.add_argument(
        "--input", "-i",
        default="data/run_outputs/anonymized_posts.jsonl",
        help="输入的帖子 JSONL 文件路径 (默认: data/run_outputs/anonymized_posts.jsonl)",
    )
    parser.add_argument(
        "--guide", "-g",
        default="docs/annotation_guide.md",
        help="标注指南 markdown 文件路径 (默认: docs/annotation_guide.md)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="data/annotations",
        help="标注输出目录 (默认: data/annotations)",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=0,
        help="限制标注条数，0=全部 (默认: 0)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="禁用 LLM 预分析，纯人工标注",
    )
    parser.add_argument(
        "--no-supplement",
        action="store_true",
        help="跳过补充字段（图像分析/Markdown备注/边界讨论），仅输出主标注字段",
    )
    parser.add_argument(
        "--media-base",
        default="data",
        help="图片本地存储根目录，用于解析 media[].ref 路径 (默认: data)",
    )
    parser.add_argument(
        "--auto-view",
        action="store_true",
        help="每条帖子自动弹出图片查看（跳过交互式选择）",
    )
    parser.add_argument(
        "--annotator-id",
        default="",
        help="直接指定标注人 ID（跳过交互式询问）",
    )
    args = parser.parse_args()

    # ── 1. 加载帖子数据 ──
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ 输入文件不存在: {input_path}")
        sys.exit(1)

    all_posts = load_jsonl(input_path)
    print(f"✅ 已加载 {len(all_posts)} 条帖子")

    # ── 2. 获取标注人 ID ──
    annotator_id = args.annotator_id.strip()
    if not annotator_id:
        annotator_id = input("请输入标注人 ID (如 D/N): ").strip()
        while not annotator_id:
            annotator_id = input("标注人 ID 不能为空，请重新输入: ").strip()

    # ── 3. 加载标注指南 ──
    guide_path = Path(args.guide)
    guide_text = load_guide(guide_path)
    if guide_path.exists():
        print(f"✅ 已加载标注指南: {guide_path}")
    else:
        print("⚠️ 标注指南文件不存在，使用内置摘要")

    # ── 4. 断点续传检测 ──
    output_dir = Path(args.output_dir)
    existing_file, completed_ids = find_existing_annotations(output_dir, annotator_id)

    output_file: Path
    if existing_file and completed_ids:
        skipped = len(completed_ids)
        print(f"\n📂 检测到已有标注文件: {existing_file}")
        print(f"   已完成 {skipped} 条，将跳过这些帖子继续标注")
        resp = input("是否继续上次标注？[Y/n]: ").strip().lower()
        if resp in ("n", "no"):
            # 创建新文件
            ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"{annotator_id}_{ts}.json"
            completed_ids = set()
            print(f"   创建新标注文件: {output_file}")
        else:
            output_file = existing_file
            print(f"   断点续传模式，已有 {skipped} 条标注")
    else:
        ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"{annotator_id}_{ts}.json"
        print(f"\n📂 新建标注文件: {output_file}")

    # ── 5. 打印标注指南 ──
    print(ANNOTATION_GUIDE_SUMMARY)

    # ── 6. 过滤待标注帖子 ──
    pending = [p for p in all_posts if p.get("post_id") not in completed_ids]
    if args.limit > 0:
        pending = pending[:args.limit]

    total_pending = len(pending)
    if total_pending == 0:
        print("✅ 所有帖子已标注完毕，无需继续！")
        return

    print(f"\n📋 本轮待标注: {total_pending} 条")
    print(f"   操作: [y] 采纳LLM建议  [n] 手动修改  [s] 跳过  [q] 退出并保存\n")

    # ── 7. 逐条标注 ──
    annotated_this_session: List[Dict[str, Any]] = []
    media_base = Path(args.media_base)

    try:
        for idx, post in enumerate(pending, 1):
            print(format_post_display(post, idx, total_pending))

            # ── 自动查看图片 ──
            if args.auto_view:
                view_images(post, media_base)

            llm_result = None
            if not args.no_llm:
                print("⏳ 正在调用 LLM 预分析...")
                llm_result = call_llm_pre_analysis(post, guide_text)
                print(format_llm_suggestion(llm_result))

            # 交互式确认
            default_label = llm_result.get("label", "非广") if llm_result else "非广"

            while True:
                action = input("操作 [y=采纳建议 / n=手动修改 / v=查看图片 / s=跳过 / q=保存退出]: ").strip().lower()

                if action == "q":
                    print("\n⏹️  用户退出，正在保存...")
                    print_stats(annotated_this_session)
                    print(f"标注文件: {output_file}")
                    return

                if action == "v":
                    view_images(post, media_base)
                    continue

                if action == "s":
                    print(f"  ⏭️  跳过 {post.get('post_id')}\n")
                    break

                if action == "y" and llm_result:
                    # 采纳 LLM 建议
                    record = make_annotation_record(
                        post_id=post["post_id"],
                        annotator_id=annotator_id,
                        label=llm_result["label"],
                        confidence=llm_result["confidence"],
                        evidence_codes=llm_result["evidence_codes"],
                        evidence=llm_result["evidence"],
                        uncertain_reason=llm_result.get("uncertain_reason"),
                        llm_suggestion=llm_result,
                        post=post,
                    )
                    # ── 可选补充字段 ──
                    if not args.no_supplement:
                        record["image_analyses"] = prompt_image_analysis(post)
                        record["markdown_notes"] = prompt_markdown_notes()
                        record["edge_case_discussion"] = prompt_edge_case()
                    append_annotation(output_file, record)
                    annotated_this_session.append(record)
                    print(f"  ✅ 已记录: {llm_result['label']} (确信度: {llm_result['confidence']:.0%})\n")
                    break

                if action in ("y", "n"):
                    # 手动标注
                    if action == "y" and not llm_result:
                        print("  ⚠️ 无 LLM 建议可采纳，进入手动模式")

                    label = prompt_label_choice(default_label)
                    evidence_codes = prompt_evidence_codes()
                    confidence = prompt_confidence()
                    evidence = prompt_evidence_text()
                    uncertain = None
                    if confidence < 0.6:
                        uncertain = input("  不确定原因（直接回车跳过）: ").strip() or None

                    record = make_annotation_record(
                        post_id=post["post_id"],
                        annotator_id=annotator_id,
                        label=label,
                        confidence=confidence,
                        evidence_codes=evidence_codes,
                        evidence=evidence,
                        uncertain_reason=uncertain,
                        llm_suggestion=llm_result,
                        post=post,
                    )
                    # ── 可选补充字段 ──
                    if not args.no_supplement:
                        record["image_analyses"] = prompt_image_analysis(post)
                        record["markdown_notes"] = prompt_markdown_notes()
                        record["edge_case_discussion"] = prompt_edge_case()
                    append_annotation(output_file, record)
                    annotated_this_session.append(record)
                    print(f"  ✅ 已记录: {label} (确信度: {confidence:.0%})\n")
                    break

                print("  无效操作，请输入 y / n / v / s / q")

        # ── 8. 完成 ──
        print("\n🎉 本轮标注全部完成！")
        print_stats(annotated_this_session)
        print(f"\n标注文件: {output_file}")
        total_done = len(completed_ids) + len(annotated_this_session)
        print(f"该标注人累计完成: {total_done} 条")

    except KeyboardInterrupt:
        print("\n\n⏹️  用户中断，已标注内容已保存。")
        print_stats(annotated_this_session)
        print(f"标注文件: {output_file}")


if __name__ == "__main__":
    main()
