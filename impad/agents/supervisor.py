"""Supervisor 主控智能体：按输入动态调度专家。

规则（《说明书》P3）：纯文本帖跳过视觉专家；没有博主历史就跳过行为专家。
当前用确定性规则路由，零成本；后续可升级为 LLM 决策路由。
"""
from __future__ import annotations
from ..state import AdCheckState


def supervisor(state: AdCheckState) -> AdCheckState:
    post = state.get("post", {})
    plan = ["nlp"]
    notes = ["NLP 专家必选"]
    if post.get("image_path") or post.get("image_url"):
        plan.append("vision")
        notes.append("检测到图片 → 调度视觉专家")
    if post.get("history"):
        plan.append("behavior")
        notes.append(f"检测到 {len(post['history'])} 条历史帖 → 调度行为专家")
    return {
        "plan": plan,
        "agent_votes": {},
        "evidence": [f"[Supervisor] 调度：{' → '.join(plan)}（{'；'.join(notes)}）"],
    }


def route_next(state: AdCheckState) -> str:
    """条件路由：按计划走下一位专家，专家跑完就交给 Judge。"""
    plan = state.get("plan") or []
    return plan[0] if plan else "judge"
