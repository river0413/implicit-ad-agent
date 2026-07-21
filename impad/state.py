"""LangGraph 的共享状态（State）定义。

图里每个节点读它、往里写；这是整个智能体系统的"共享上下文"。
起步只放最少字段，后续按《说明书》扩展（如 memory、rag_refs、agent_votes 等）。
"""
from __future__ import annotations
from typing import Dict, List, TypedDict


class AdCheckState(TypedDict, total=False):
    post: dict          # 输入帖子：{text, blogger?, image_url?, image_path?, comments?, history?}
    plan: List[str]     # Supervisor 排好的待访问专家队列，专家跑完自我移除
    agent_votes: Dict[str, dict]  # 各专家投票：{name: {verdict, confidence, evidence}}
    keyword_weights: Dict[str, float]  # 6 维可解释特征（促销/价格/紧迫/品牌/行动/自然）
    vision_findings: dict  # 视觉专家的结构化结果：{objects, focus, texts}
    evidence: List[str]  # 逐步累积的证据链
    verdict: str        # 明广 / 暗广 / 非广（Judge 聚合后的最终判定）
    confidence: float   # 0-1 置信度
    report: str         # 最终可读报告
