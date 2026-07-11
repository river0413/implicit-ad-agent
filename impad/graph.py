"""项目起点：一个最小的"单体智能体"图。

让 LLM 判定帖子属于 明广 / 暗广 / 非广，并给出置信度与证据链。
运行需在 .env 配好 LLM（和可选的 LangSmith）。
后续按《说明书》把这里扩成 Supervisor + 专家(NLP/视觉/行为) + Judge 的多智能体图。
"""
from __future__ import annotations
from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from .state import AdCheckState
from .llm import get_llm


class Judgement(BaseModel):
    verdict: str = Field(description="只能是 明广 / 暗广 / 非广 之一")
    confidence: float = Field(description="0-1 的置信度")
    evidence: list[str] = Field(description="支撑该判定的证据，逐条列出")


PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是社交媒体隐性广告审查员。请判断给定帖子属于：\n"
     "· 明广：明确标注广告/赞助/合作；\n"
     "· 暗广：未标注但有明显导购意图或软广话术（制造焦虑、亲身体验、引导购买等）；\n"
     "· 非广：正常内容分享。\n"
     "给出判定、0-1 置信度，以及可解释的证据链。\n"
     "请以 JSON 格式输出，且必须严格使用以下英文字段名（不要翻译成中文）：\n"
     "- verdict: 字符串，只能是 \"明广\"、\"暗广\"、\"非广\" 之一\n"
     "- confidence: 0到1之间的浮点数\n"
     "- evidence: 字符串数组，每条为一个证据\n"
     "示例格式：{{\"verdict\": \"暗广\", \"confidence\": 0.95, \"evidence\": [\"证据1\", \"证据2\"]}}"),
    ("human", "博主：{blogger}\n正文：{text}\n评论区：{comments}"),
])


def analyze(state: AdCheckState) -> AdCheckState:
    post = state.get("post", {})
    llm = get_llm().with_structured_output(Judgement, method="json_mode")
    messages = PROMPT.format_messages(
        blogger=post.get("blogger", "未知"),
        text=post.get("text", ""),
        comments="；".join(post.get("comments", [])) or "（无）",
    )
    j: Judgement = llm.invoke(messages)
    report = (f"判定：{j.verdict}（置信度 {j.confidence:.2f}）\n证据链：\n"
              + "\n".join(f"  - {e}" for e in j.evidence))
    return {"verdict": j.verdict, "confidence": j.confidence,
            "evidence": j.evidence, "report": report}


def build_graph():
    g = StateGraph(AdCheckState)
    g.add_node("analyze", analyze)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", END)
    return g.compile()


graph = build_graph()


if __name__ == "__main__":
    sample = {"post": {
        "text": "这支面霜我亲测三个月，无限回购，链接在评论区，姐妹们码住！",
        "blogger": "小美的日常", "comments": ["求链接", "已买"]}}
    print(graph.invoke(sample)["report"])
