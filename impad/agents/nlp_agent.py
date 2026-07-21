"""NLP 专家智能体：分析文案的导购意图、软广话术。

配好 .env 时走 LLM；未配 Key 时自动降级为关键词规则，保证全图零成本可跑。
两条路径都会附带一份确定性的 6 维关键词权重（compute_keyword_weights），
作为可解释特征供 Judge 聚合与前端/论文使用。

注意：结构化输出用 method="json_mode" 且 prompt 强制英文字段名，
这是为兼容 DeepSeek 等国产端点的有意设计，不要改回默认 function-calling。
6 维权重刻意在代码里确定性计算，而不是让 LLM 吐嵌套 JSON——避开国产端点
对复杂结构化输出不稳的坑，同时保证规则降级路径也有同样的特征。
"""
from __future__ import annotations
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from ..config import settings
from ..llm import get_llm
from ..state import AdCheckState
from ..tools.keywords import (EXPLICIT_AD_MARKERS, SOFT_AD_SIGNALS,
                              compute_keyword_weights, ad_pressure, summarize_weights)


class Judgement(BaseModel):
    verdict: str = Field(description="只能是 明广 / 暗广 / 非广 之一")
    confidence: float = Field(description="0-1 的置信度")
    evidence: list[str] = Field(description="支撑该判定的证据，逐条列出")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是社交媒体隐性广告审查员，只负责文本分析。请把给定帖子判为三类之一：\n"
     "· 明广：明确标注广告/赞助/合作/推广，推广意图公开；\n"
     "· 暗广：未标注广告，但以分享、测评、种草、亲身体验等自然形式包装，"
     "实则引导消费（如刻意夸赞单品、制造焦虑与紧迫、引流到链接/评论区/私信）；\n"
     "· 非广：纯粹的情感表达、生活记录、观点交流，不含任何推广或引导消费。\n"
     "判断要点：明广看是否有公开的广告标识；暗广看'自然表达的外壳 + 导购内核'的反差；"
     "非广则通篇无商业指向。给出判定、0-1 置信度，以及可解释的证据链。\n"
     "请以 JSON 格式输出，且必须严格使用以下英文字段名（不要翻译成中文）：\n"
     "- verdict: 字符串，只能是 \"明广\"、\"暗广\"、\"非广\" 之一\n"
     "- confidence: 0到1之间的浮点数\n"
     "- evidence: 字符串数组，每条为一个证据\n"
     "示例格式：{{\"verdict\": \"暗广\", \"confidence\": 0.95, \"evidence\": [\"证据1\", \"证据2\"]}}"),
    ("human", "博主：{blogger}\n正文：{text}\n评论区：{comments}"),
])


def _llm_judge(post: dict) -> Judgement:
    llm = get_llm().with_structured_output(Judgement, method="json_mode")
    messages = PROMPT.format_messages(
        blogger=post.get("blogger", "未知"),
        text=post.get("text", ""),
        comments="；".join(post.get("comments", [])) or "（无）",
    )
    return llm.invoke(messages)


def _rule_judge(post: dict, weights: dict[str, float]) -> Judgement:
    text = post.get("text", "")
    explicit = [w for w in EXPLICIT_AD_MARKERS if w in text]
    if explicit:
        return Judgement(verdict="明广", confidence=0.9,
                         evidence=[f"命中明广标识：{', '.join(explicit)}"])
    soft = [w for w in SOFT_AD_SIGNALS if w in text]
    if soft:
        return Judgement(verdict="暗广", confidence=min(0.5 + 0.1 * len(soft), 0.95),
                         evidence=[f"命中软广信号词：{', '.join(soft)}"])
    # 兜底层：软广词没命中，但 6 维权重显示强导购压力且盖过自然表达 → 暗广
    pressure = ad_pressure(weights)
    if pressure >= 0.5 and pressure > weights["natural_expression"]:
        return Judgement(verdict="暗广", confidence=round(min(0.5 + pressure * 0.4, 0.9), 2),
                         evidence=[f"未命中软广词，但导购压力偏高（{pressure:.2f}）：{summarize_weights(weights)}"])
    return Judgement(verdict="非广", confidence=0.6, evidence=["未命中广告信号词"])


def nlp_agent(state: AdCheckState) -> AdCheckState:
    post = state.get("post", {})
    weights = compute_keyword_weights(post.get("text", ""))
    if settings.openai_api_key:
        j, source = _llm_judge(post), "LLM"
    else:
        j, source = _rule_judge(post, weights), "规则降级·未配Key"

    vote = {"verdict": j.verdict, "confidence": j.confidence,
            "evidence": j.evidence, "keyword_weights": weights}
    evidence = state.get("evidence", []) + [f"[NLP·{source}] {e}" for e in j.evidence]
    if any(v > 0 for v in weights.values()):
        evidence.append(f"[NLP·特征] 关键词权重 → {summarize_weights(weights)}")
    return {
        "agent_votes": {**state.get("agent_votes", {}), "nlp": vote},
        "keyword_weights": weights,
        "evidence": evidence,
        "plan": [a for a in state.get("plan", []) if a != "nlp"],
    }
