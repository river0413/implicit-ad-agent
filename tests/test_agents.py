"""多智能体图测试：路由、加权聚合、全图零 Key 跑通（不调用真实 LLM）。"""
from impad.agents import supervisor, route_next, judge
from impad.config import settings
from impad.graph import graph


def test_supervisor_routes_by_input():
    # 纯文本 → 只派 NLP
    assert supervisor({"post": {"text": "hi"}})["plan"] == ["nlp"]
    # 有图有历史 → 全开
    out = supervisor({"post": {"text": "hi", "image_url": "x.jpg", "history": ["a"]}})
    assert out["plan"] == ["nlp", "vision", "behavior"]


def test_route_next_falls_back_to_judge():
    assert route_next({"plan": ["vision", "behavior"]}) == "vision"
    assert route_next({"plan": []}) == "judge"


def test_judge_weighted_aggregation():
    out = judge({"agent_votes": {
        "nlp": {"verdict": "暗广", "confidence": 0.9, "evidence": []},
        "behavior": {"verdict": "非广", "confidence": 0.2, "evidence": []},
        "vision": {"verdict": "非广", "confidence": 0.0, "evidence": []},  # 空票应被忽略
    }})
    assert out["verdict"] == "暗广"
    assert 0.0 < out["confidence"] <= 1.0
    assert out["report"]


def test_full_graph_zero_key(monkeypatch):
    # 强制走规则降级路径，保证测试不花钱、不联网
    monkeypatch.setattr(settings, "openai_api_key", "")
    out = graph.invoke({"post": {
        "text": "这支面霜我亲测三个月，无限回购，链接在评论区",
        "blogger": "x",
        "history": ["今天天气不错", "读书笔记分享"]}})
    assert out["verdict"] in {"明广", "暗广", "非广"}
    assert "nlp" in out["agent_votes"] and "behavior" in out["agent_votes"]
    assert "vision" not in out["agent_votes"]  # 无图不应调度视觉专家
    assert out["report"]
