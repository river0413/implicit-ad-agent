"""最小可跑的 LangGraph 示例：无需任何 API Key。

作用：验证环境是否装好、LangSmith 轨迹是否打通。
流程：ingest（读入帖子）→ classify（规则占位判断）→ report（生成报告）。
真正的智能体逻辑见 graph.py；这里只是用规则占位，好让你零成本先看到"图能跑、轨迹能出"。
"""
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from .state import AdCheckState
from .tools.keywords import SOFT_AD_SIGNALS, compute_keyword_weights, summarize_weights


def ingest(state: AdCheckState) -> AdCheckState:
    text = state.get("post", {}).get("text", "")
    return {"evidence": [f"读入帖子，正文长度 {len(text)} 字"]}


def classify(state: AdCheckState) -> AdCheckState:
    text = state.get("post", {}).get("text", "")
    weights = compute_keyword_weights(text)
    hits = [w for w in SOFT_AD_SIGNALS if w in text]
    if hits:
        verdict, conf = "暗广", min(0.5 + 0.1 * len(hits), 0.95)
        note = f"命中软广信号词：{', '.join(hits)}"
    else:
        verdict, conf = "非广", 0.6
        note = "未命中明显软广信号词"
    notes = [note, f"关键词权重 → {summarize_weights(weights)}"]
    return {"verdict": verdict, "confidence": conf, "keyword_weights": weights,
            "evidence": state.get("evidence", []) + notes}


def report(state: AdCheckState) -> AdCheckState:
    lines = [f"判定：{state.get('verdict')}（置信度 {state.get('confidence'):.2f}）", "证据链："]
    lines += [f"  - {e}" for e in state.get("evidence", [])]
    return {"report": "\n".join(lines)}


def build_graph():
    g = StateGraph(AdCheckState)
    g.add_node("ingest", ingest)
    g.add_node("classify", classify)
    g.add_node("report", report)
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "classify")
    g.add_edge("classify", "report")
    g.add_edge("report", END)
    return g.compile()


graph = build_graph()


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sample = {"post": {
        "text": "这支面霜我亲测三个月，无限回购，链接在评论区，姐妹们码住！",
        "blogger": "小美的日常"}}
    print(graph.invoke(sample)["report"])
