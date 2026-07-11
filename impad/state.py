"""LangGraph 的共享状态（State）定义。

图里每个节点读它、往里写；这是整个智能体系统的"共享上下文"。
起步只放最少字段，后续按《说明书》扩展（如 memory、rag_refs、agent_votes 等）。
"""
from __future__ import annotations
from typing import List, TypedDict


class AdCheckState(TypedDict, total=False):
    post: dict          # 输入帖子：{text, blogger?, image_url?, comments?}
    evidence: List[str]  # 逐步累积的证据链
    verdict: str        # 明广 / 暗广 / 非广
    confidence: float   # 0-1 置信度
    report: str         # 最终可读报告
