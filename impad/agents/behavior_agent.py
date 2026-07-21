"""行为专家智能体（占位规则版）：检测博主人设/主题偏移。

思路（《说明书》P3）：博主长期不发导购内容、某天突然出现软广话术 = 疑似接单。
当前用"历史命中率 vs 当前命中"的简化规则；
后续升级为 EMA 偏好偏移 + Chroma 情景记忆。
"""
from __future__ import annotations
from ..state import AdCheckState
from ..tools.keywords import SOFT_AD_SIGNALS


def behavior_agent(state: AdCheckState) -> AdCheckState:
    post = state.get("post", {})
    history: list[str] = post.get("history", [])
    cur_hit = any(w in post.get("text", "") for w in SOFT_AD_SIGNALS)
    hist_hits = sum(1 for h in history if any(w in h for w in SOFT_AD_SIGNALS))

    if history and cur_hit and hist_hits / len(history) < 0.3:
        vote = {"verdict": "暗广", "confidence": 0.4, "evidence": [
            f"人设偏移：历史 {hist_hits}/{len(history)} 条含导购话术，当前帖突然出现，疑似接单"]}
    else:
        vote = {"verdict": "非广", "confidence": 0.2, "evidence": [
            f"历史 {hist_hits}/{len(history)} 条含导购话术，与当前帖无明显断裂"
            "（占位规则，EMA+Chroma 记忆待接入 P3）"]}

    return {
        "agent_votes": {**state.get("agent_votes", {}), "behavior": vote},
        "evidence": state.get("evidence", []) + [f"[行为] {e}" for e in vote["evidence"]],
        "plan": [a for a in state.get("plan", []) if a != "behavior"],
    }
