"""Judge 聚合智能体：按各专家可靠度加权投票，产出最终判定与报告。

借鉴 2508.10143《MCP 编排多智能体虚假信息检测》的加权聚合思路。
权重先手工设定，P4 评估阶段用验证集上各专家的实际误判率反推校准。
低置信时记录反思质询问题（反思回路——重新质询专家——P3 接入）。
"""
from __future__ import annotations
from ..state import AdCheckState
from ..tools.keywords import summarize_weights

# 各专家可靠度权重（未列入的智能体按 0.1 兜底）
WEIGHTS = {"nlp": 0.6, "vision": 0.25, "behavior": 0.15}
REFLECT_THRESHOLD = 0.55  # 低于此置信度触发反思质询


def judge(state: AdCheckState) -> AdCheckState:
    votes = state.get("agent_votes", {})
    scores: dict[str, float] = {}
    total_w = 0.0
    for name, v in votes.items():
        conf = v.get("confidence", 0.0)
        if conf <= 0:  # 占位专家投空票，不计入
            continue
        w = WEIGHTS.get(name, 0.1)
        scores[v["verdict"]] = scores.get(v["verdict"], 0.0) + w * conf
        total_w += w

    if scores:
        verdict = max(scores, key=scores.get)
        confidence = round(scores[verdict] / total_w, 2)
    else:
        verdict, confidence = "非广", 0.0

    evidence = list(state.get("evidence", []))
    detail = "，".join(f"{k} {v:.2f}" for k, v in scores.items()) or "无有效投票"
    evidence.append(f"[Judge] 加权聚合（{detail}）→ {verdict}（置信度 {confidence:.2f}）")

    weights = state.get("keyword_weights", {})
    if weights and any(v > 0 for v in weights.values()):
        evidence.append(f"[Judge] 可解释特征参考：{summarize_weights(weights)}")
    if confidence < REFLECT_THRESHOLD:
        evidence.append("[Judge·反思] 置信度偏低，质询：文案痛点与图片焦点一致吗？"
                        "历史人设与当前推荐断裂吗？（反思回路待接入 P3）")

    lines = [f"判定：{verdict}（置信度 {confidence:.2f}）", "各专家投票："]
    for name, v in votes.items():
        lines.append(f"  · {name}：{v['verdict']}（{v.get('confidence', 0):.2f}）")
    lines.append("证据链：")
    lines += [f"  - {e}" for e in evidence]

    return {"verdict": verdict, "confidence": confidence,
            "keyword_weights": weights,
            "evidence": evidence, "report": "\n".join(lines)}
