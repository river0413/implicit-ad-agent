#!/usr/bin/env python3
"""
双 LLM 交叉验证：从微信文章中提取图片位置和标注文字。

替代纯正则表达式方案：
  - LLM-A (temperature=0): 分析文档结构，识别图片位置、提取标注、插入 <图片N> 标记
  - LLM-B (temperature=0.3): 独立验证 LLM-A 的结果
  - 不一致或置信度低时标记 needs_review

使用 DeepSeek API（通过 impad.llm 的 OpenAI 兼容端点）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# 确保项目根目录在 path 中，能 import impad
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from impad.llm import get_llm


# ═══════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════

PROMPT_EXTRACT = """你是一个文档结构分析专家。分析以下微信文章，完成三个任务。

## 背景
文章正文中插入了 {image_count} 张图片。你需要找出每张图片的准确位置和下方的标注文字。

## 图片 URL（按出现顺序）

{image_url_list}

## 任务

1. **定位图片位置**：判断每张图片插入在正文的哪两段文字之间。
   在正文中对应位置插入标记：<图片1>、<图片2>……（图片N 对应上面第 N 个 URL）。
   如果某张图片是装饰性/图标类（非内容图片），不要为它插入标记，在 notes 中说明。

2. **提取图片标注**：微信文章中，图片下方常有摄影记者署名或说明文字。
   例如："新华社记者 刘大伟 摄"、"2021年8月4日，中国组合许昕/马龙（右）在东京奥运会..."。
   把每张内容图片的标注文字提取出来，没有标注则 caption 填 null。

3. **区分内容图与装饰图**：只处理内容图片（照片、截图、产品图等）。
   跳过二维码、公众号头像、SVG占位符、表情包小图等装饰性图片。

## 输出格式（严格 JSON，不要有其他文字）

```json
{{
  "text_with_markers": "在此输出插入<图片1><图片2>标记后的完整正文（仅内容图片有标记）",
  "image_analysis": [
    {{
      "url_index": 1,
      "is_content": true,
      "caption": "图片标注文字，没有则填 null",
      "position_hint": "图片前后的文字片段（用于校验）"
    }}
  ],
  "confidence": 0.9,
  "notes": "任何说明或不确定之处，包括哪些图片被判定为装饰图及原因"
}}
```

## 正文

{article_text}"""


PROMPT_VERIFY = """你是一个严谨的文档校对专家。下面是同一篇微信文章，以及另一位分析师的分析结果。请独立判断分析是否准确。

## 原始正文

{article_text}

## 待验证的分析结果

分析师输出的带标记正文：
```
{text_with_markers}
```

图片标注提取结果：
```json
{image_analysis}
```

## 你的任务

独立分析原始正文，逐项验证：

1. <图片N> 标记是否在正确的位置？
2. 每张图片的标注文字是否准确提取？有无遗漏或多提取？
3. 是否有内容图片被漏标，或装饰图片被误标为内容图？
4. 标注文字中是否混入了正文段落文字（而非真正的图片标注）？

## 输出格式（严格 JSON，不要有其他文字）

```json
{{
  "is_consistent": true,
  "issues": [
    {{"type": "wrong_position|wrong_caption|missing_marker|extra_marker", "detail": "具体问题"}}
  ],
  "corrected_text_with_markers": "如有修正输出完整正文，无修正填 null",
  "corrected_image_analysis": [],
  "confidence": 0.9,
  "notes": "验证说明"
}}
```

- 如果分析完全正确，`is_consistent` 为 true，`issues` 为空数组。
- 如果有细微问题但可自动修正，在 `corrected_*` 中提供修正版。
- 如果有严重问题（如图片完全错位），`is_consistent` 为 false，在 `issues` 中详细说明。"""


# ═══════════════════════════════════════════════════════════════
# LLM 调用
# ═══════════════════════════════════════════════════════════════

def _parse_json_response(text: str) -> Dict:
    """从 LLM 响应中健壮地提取 JSON 对象。"""
    text = text.strip()

    # 去掉 markdown 代码块包裹
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    # 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 用正则匹配最外层 {...}
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 响应解析 JSON（前 300 字符）:\n{text[:300]}")


def _invoke_llm(prompt: str, temperature: float, max_tokens: int = 4096) -> str:
    """调用 LLM 并返回文本响应。"""
    llm = get_llm(temperature=temperature, max_tokens=max_tokens)
    response = llm.invoke(prompt)
    # LangChain ChatOpenAI 返回 AIMessage，其 .content 是字符串
    return response.content if hasattr(response, "content") else str(response)


# ═══════════════════════════════════════════════════════════════
# 核心流程
# ═══════════════════════════════════════════════════════════════

def _extract_with_llm_a(
    article_text: str,
    image_urls: List[str],
    timeout_seconds: int = 60,
) -> Dict:
    """LLM-A: 分析文档结构，提取图片位置和标注。"""
    url_list_text = "\n".join(
        f"  URL {i+1}: {url}" for i, url in enumerate(image_urls)
    )

    prompt = PROMPT_EXTRACT.format(
        image_count=len(image_urls),
        image_url_list=url_list_text,
        article_text=article_text,
    )

    raw = _invoke_llm(prompt, temperature=0.0)
    return _parse_json_response(raw)


def _verify_with_llm_b(
    article_text: str,
    text_with_markers: str,
    image_analysis: List[Dict],
    timeout_seconds: int = 60,
) -> Dict:
    """LLM-B: 独立验证 LLM-A 的分析结果。"""
    prompt = PROMPT_VERIFY.format(
        article_text=article_text,
        text_with_markers=text_with_markers,
        image_analysis=json.dumps(image_analysis, ensure_ascii=False, indent=2),
    )

    raw = _invoke_llm(prompt, temperature=0.3)
    return _parse_json_response(raw)


def dual_llm_extract(
    article_text: str,
    image_urls: List[str],
    agreement_threshold: float = 0.6,
    skip_if_no_images: bool = True,
) -> Dict:
    """
    双 LLM 交叉验证：提取图片位置和标注。

    Args:
        article_text: 清洗后的文章正文（不含图片标记）
        image_urls: 从 HTML 中提取的原始图片 URL 列表（含可能的装饰图）
        agreement_threshold: 双 LLM 置信度均值低于此值时标记 needs_review
        skip_if_no_images: 无图片时直接返回原文

    Returns:
        {
            "text_with_markers": str,       # 带 <图片N> 标记的正文
            "media_enrichments": [            # 每张图（索引0开始）的补充信息
                {"index": 0, "is_content": bool, "caption": str|null}
            ],
            "verified": bool,                # LLM-B 认为 LLM-A 结果一致
            "llm_a_confidence": float,
            "llm_b_confidence": float,
            "needs_review": bool,            # 需人工复核
            "review_reason": str,
            "notes": str,
        }
    """
    if not image_urls:
        return {
            "text_with_markers": article_text,
            "media_enrichments": [],
            "verified": True,
            "llm_a_confidence": 1.0,
            "llm_b_confidence": 1.0,
            "needs_review": False,
            "review_reason": "",
            "notes": "无图片，跳过 LLM 分析",
        }

    # ── LLM-A: 主提取 ──
    print("    [LLM-A] 分析文档结构（{0} 张图，{1} 字）...".format(
        len(image_urls), len(article_text)))
    try:
        result_a = _extract_with_llm_a(article_text, image_urls)
    except Exception as exc:
        print(f"    [LLM-A] 失败: {exc}")
        return _fallback_result(article_text, image_urls, str(exc))

    time.sleep(0.5)  # 礼貌间隔

    # ── LLM-B: 验证 ──
    text_with_markers_a = result_a.get("text_with_markers", article_text)
    image_analysis_a = result_a.get("image_analysis", [])
    confidence_a = result_a.get("confidence", 0.5)

    print("    [LLM-B] 独立验证...")
    try:
        result_b = _verify_with_llm_b(
            article_text, text_with_markers_a, image_analysis_a
        )
    except Exception as exc:
        print(f"    [LLM-B] 失败: {exc}，采用 LLM-A 结果")
        # LLM-B 失败时，信任 LLM-A 但标记需复核
        return _build_result(
            article_text, image_urls, result_a,
            verified=False,
            confidence_b=0.0,
            needs_review=True,
            review_reason=f"LLM-B 验证失败: {exc}",
        )

    # ── 交叉验证 ──
    is_consistent = result_b.get("is_consistent", False)
    confidence_b = result_b.get("confidence", 0.5)
    avg_confidence = (confidence_a + confidence_b) / 2
    needs_review = (not is_consistent) or (avg_confidence < agreement_threshold)

    # 用修正版（如有）
    corrected_text = result_b.get("corrected_text_with_markers")
    corrected_analysis = result_b.get("corrected_image_analysis")
    issues = result_b.get("issues", [])

    final_text = corrected_text if corrected_text and is_consistent else text_with_markers_a
    final_analysis = corrected_analysis if corrected_analysis and is_consistent else image_analysis_a

    # 构建 media_enrichments（对齐 image_urls 的索引 0..N-1）
    # image_analysis 中的 url_index 是 1-based
    analysis_by_index: Dict[int, Dict] = {}
    for item in final_analysis:
        idx = item.get("url_index", -1)
        if isinstance(idx, int) and idx >= 1:
            analysis_by_index[idx - 1] = item  # 转为 0-based

    media_enrichments = []
    for i, url in enumerate(image_urls):
        info = analysis_by_index.get(i, {})
        media_enrichments.append({
            "index": i,
            "is_content": info.get("is_content", True),
            "caption": info.get("caption"),
        })

    # 构建 review_reason
    review_reason = ""
    if not is_consistent:
        review_reason = f"LLM-B 判定不一致; issues: {json.dumps(issues, ensure_ascii=False)[:300]}"
    elif avg_confidence < agreement_threshold:
        review_reason = f"置信度过低: A={confidence_a:.2f}, B={confidence_b:.2f}"

    print(f"    ✓ 完成: 一致={is_consistent}, 置信度 A={confidence_a:.2f} B={confidence_b:.2f}")

    return {
        "text_with_markers": final_text,
        "media_enrichments": media_enrichments,
        "verified": is_consistent,
        "llm_a_confidence": confidence_a,
        "llm_b_confidence": confidence_b,
        "needs_review": needs_review,
        "review_reason": review_reason,
        "notes": result_a.get("notes", ""),
    }


def _fallback_result(
    article_text: str, image_urls: List[str], error_msg: str
) -> Dict:
    """LLM 完全失败时的兜底结果。"""
    return {
        "text_with_markers": article_text,
        "media_enrichments": [
            {"index": i, "is_content": True, "caption": None}
            for i in range(len(image_urls))
        ],
        "verified": False,
        "llm_a_confidence": 0.0,
        "llm_b_confidence": 0.0,
        "needs_review": True,
        "review_reason": f"LLM 提取失败: {error_msg}",
        "notes": error_msg,
    }


def _build_result(
    article_text: str,
    image_urls: List[str],
    result_a: Dict,
    verified: bool,
    confidence_b: float,
    needs_review: bool,
    review_reason: str,
) -> Dict:
    """从 LLM-A 结果构建返回值（LLM-B 不可用时）。"""
    analysis = result_a.get("image_analysis", [])
    analysis_by_index: Dict[int, Dict] = {}
    for item in analysis:
        idx = item.get("url_index", -1)
        if isinstance(idx, int) and idx >= 1:
            analysis_by_index[idx - 1] = item

    return {
        "text_with_markers": result_a.get("text_with_markers", article_text),
        "media_enrichments": [
            {
                "index": i,
                "is_content": analysis_by_index.get(i, {}).get("is_content", True),
                "caption": analysis_by_index.get(i, {}).get("caption"),
            }
            for i in range(len(image_urls))
        ],
        "verified": verified,
        "llm_a_confidence": result_a.get("confidence", 0.5),
        "llm_b_confidence": confidence_b,
        "needs_review": needs_review,
        "review_reason": review_reason,
        "notes": result_a.get("notes", ""),
    }


# ═══════════════════════════════════════════════════════════════
# HTML 直分析模式：LLM 从原始 HTML 提取纯净正文 + 图片位置
# ═══════════════════════════════════════════════════════════════

def _preprocess_html(html: str, max_chars: int = 20000) -> str:
    """预处理 HTML：去 script/style/注释，剥离标签属性，压缩空白。"""
    # 1. 删除 script / style / 注释
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<!--[\s\S]*?-->", "", html)

    # 2. 剥离标签属性（style/class/id/data-*/width/height 等），只保留标签名和 src
    #    微信文章 HTML 中 style 属性动辄几百字符，全是噪声
    def _strip_attrs(m: re.Match) -> str:
        tag = m.group(1)
        inner = m.group(2)
        # 保留 src 和 data-src（图片 URL 关键属性）
        src = ""
        m_src = re.search(r"""(?:data-)?src\s*=\s*["']([^"']+)["']""", inner, re.IGNORECASE)
        if m_src:
            src = f' src="{m_src.group(1)}"'
        return f"<{tag}{src}>"

    html = re.sub(r"<(\w+)(\s[^>]*)>", _strip_attrs, html, flags=re.IGNORECASE)

    # 3. 删除纯结构空标签（无文本内容的嵌套 div/span/section）
    html = re.sub(r"<(div|span|section|p|a|ul|ol|li|h[1-6]|blockquote)>\s*</\1>", "", html, flags=re.IGNORECASE)

    # 4. 压缩空白
    html = re.sub(r"\s+", " ", html)
    html = html.strip()

    if len(html) > max_chars:
        html = html[:max_chars] + "\n...(truncated)"
    return html


PROMPT_FROM_HTML = """你是一个微信文章解析专家。请从以下微信文章 HTML 中提取纯净内容。

{chunk_hint}

## 任务

1. **提取标题**：从 <title> 标签提取文章标题，去除公众号名称后缀。

2. **提取纯净正文**：只保留文章的自然语言正文。严格删除所有微信界面元素：
   赞赏/留言/导航/关注/分享按钮、公众号信息、验证警告、"阅读 9999"等统计、
   "原创 作者名"、日期行、"来源：XXX 记者：XXX"、HTML标签残留、&nbsp;等。
   只保留文章正文的段落文字。

3. **处理图片**：正文中有 {image_count} 张图片，URL：
   {image_url_list}
   在正文对应位置插入 <图片{start_num}>、<图片{start_num_plus_1}>... 标记。
   装饰图/图标不标记，在 notes 说明。

   单独记录每张内容图片的标注文字到 image_captions（如"新华社记者 XXX 摄"）。

## 输出（严格 JSON）

```json
{{
  "title": "纯净标题",
  "clean_text": "带<图片N>标记的纯净正文",
  "image_captions": [{{"index": 1, "is_content": true, "caption": "标注或null"}}],
  "confidence": 0.9,
  "notes": ""
}}
```

## HTML

{html_content}"""


def _llm_extract_single(
    html_chunk: str, image_urls: List[str],
    start_image_num: int = 1, is_chunk: bool = False, chunk_info: str = "",
) -> Dict:
    """单次 LLM 提取（用于整篇或单个分块）。"""
    if not html_chunk:
        return {"title": None, "clean_text": "", "media_enrichments": [],
                "confidence": 1.0, "needs_review": False, "notes": "空输入"}

    url_list_text = "\n".join(
        f"  URL {i+1}: {url}" for i, url in enumerate(image_urls)
    ) if image_urls else "（无图片）"

    start_plus_1 = start_image_num + 1

    chunk_hint = ""
    if is_chunk:
        chunk_hint = f"（注意：这是文章的分段 {chunk_info}，图片编号从 <图片{start_image_num}> 开始）"

    prompt = PROMPT_FROM_HTML.format(
        chunk_hint=chunk_hint, image_count=len(image_urls),
        image_url_list=url_list_text, start_num=start_image_num,
        start_num_plus_1=start_plus_1, html_content=html_chunk)

    try:
        raw = _invoke_llm(prompt, temperature=0.0, max_tokens=4096)
        result = _parse_json_response(raw)
    except Exception as exc:
        print(f"    [LLM-HTML] 失败: {exc}")
        return {"title": None, "clean_text": "", "media_enrichments": [
            {"index": i, "is_content": True, "caption": None} for i in range(len(image_urls))],
            "confidence": 0.0, "needs_review": True, "notes": str(exc)}
    return result


def llm_extract_from_html(html: str, image_urls: List[str],
                          chunk_size: int = 12000) -> Dict:
    """
    单 LLM 从原始 HTML 直接提取：纯净标题 + 纯净正文（含<图片N>标记）+ 图片标注。

    长文自动分块接力处理：每块传递上一块最后图片编号。max_tokens=4096。
    """
    if not html:
        return {"title": None, "clean_text": "", "media_enrichments": [],
                "confidence": 1.0, "needs_review": False, "notes": "无 HTML"}

    clean_html = _preprocess_html(html, max_chars=999999)
    total_len = len(clean_html)
    total_images = len(image_urls)

    # ── 短文：一次处理 ──
    if total_len <= chunk_size:
        clean_html = clean_html[:chunk_size]
        print(f"    [LLM-HTML] 短文模式 ({total_len} 字符, {total_images} 图)...")
        result = _llm_extract_single(clean_html, image_urls, start_image_num=1)
        return _build_llm_result(result, image_urls, total_len)

    # ── 长文：分块接力 ──
    print(f"    [LLM-HTML] 长文模式 ({total_len} 字符 → 分块, {total_images} 图)...")

    num_chunks = (total_len + chunk_size - 1) // chunk_size
    imgs_per_chunk = max(1, total_images // num_chunks) if total_images else 0

    all_clean_text = ""
    all_enrichments: List[Dict] = []
    llm_title = None
    last_img_idx = 0
    total_confidence = 0.0
    needs_review = False
    all_notes = []

    for chunk_idx in range(num_chunks):
        start_pos = chunk_idx * chunk_size
        end_pos = min(start_pos + chunk_size, total_len)
        chunk_html = clean_html[start_pos:end_pos]

        chunk_start_img = last_img_idx
        chunk_end_img = min(chunk_start_img + imgs_per_chunk, total_images)
        if chunk_idx == num_chunks - 1:
            chunk_end_img = total_images
        chunk_images = image_urls[chunk_start_img:chunk_end_img]

        chunk_info = f"第 {chunk_idx + 1}/{num_chunks} 段"
        print(f"    [LLM-HTML] 分块 {chunk_idx + 1}/{num_chunks}: "
              f"图 {chunk_start_img + 1}-{chunk_end_img}")

        result = _llm_extract_single(
            chunk_html, chunk_images,
            start_image_num=last_img_idx + 1, is_chunk=True, chunk_info=chunk_info)

        if not llm_title and result.get("title"):
            llm_title = result["title"]

        chunk_text = result.get("clean_text", "")
        if chunk_text:
            all_clean_text += chunk_text + "\n"

        captions = result.get("image_captions", [])
        for cap in captions:
            idx = cap.get("index", -1)
            if isinstance(idx, int) and idx >= 1:
                global_idx = chunk_start_img + (idx - 1)
                if global_idx < total_images:
                    all_enrichments.append({
                        "index": global_idx, "is_content": cap.get("is_content", True),
                        "caption": cap.get("caption")})

        total_confidence += result.get("confidence", 0.5)
        if result.get("needs_review", False):
            needs_review = True
        if result.get("notes"):
            all_notes.append(f"[块{chunk_idx + 1}] {result['notes']}")

        last_img_idx = chunk_end_img
        if chunk_idx < num_chunks - 1:
            time.sleep(0.3)

    # 兜底：未被任何块覆盖的图片
    covered = {e["index"] for e in all_enrichments}
    for i in range(total_images):
        if i not in covered:
            all_enrichments.append({"index": i, "is_content": True, "caption": None})

    avg_conf = total_confidence / num_chunks if num_chunks else 0.5

    print(f"    [LLM-HTML] 分块完成: {num_chunks} 块 → 正文 {len(all_clean_text)} 字, "
          f"平均置信度 {avg_conf:.2f}")

    return {"title": llm_title, "clean_text": all_clean_text.strip(),
            "media_enrichments": sorted(all_enrichments, key=lambda x: x["index"]),
            "confidence": round(avg_conf, 2),
            "needs_review": needs_review or avg_conf < 0.6,
            "notes": "; ".join(all_notes) if all_notes else ""}


def _build_llm_result(result: Dict, image_urls: List[str], total_len: int) -> Dict:
    """从单次 LLM 结果构建标准返回值。"""
    llm_title = result.get("title")
    clean_text = result.get("clean_text", "")
    captions = result.get("image_captions", [])

    caption_by_index = {}
    for cap in captions:
        idx = cap.get("index", -1)
        if isinstance(idx, int) and idx >= 1:
            caption_by_index[idx - 1] = cap

    media_enrichments = []
    for i in range(len(image_urls)):
        info = caption_by_index.get(i, {})
        media_enrichments.append({
            "index": i, "is_content": info.get("is_content", True),
            "caption": info.get("caption")})

    confidence = result.get("confidence", 0.5)
    print(f"    [LLM-HTML] 完成: 正文 {len(clean_text)} 字 ({total_len} 字符输入), 置信度 {confidence:.2f}")
    return {"title": llm_title, "clean_text": clean_text,
            "media_enrichments": media_enrichments, "confidence": confidence,
            "needs_review": confidence < 0.6, "notes": result.get("notes", "")}
