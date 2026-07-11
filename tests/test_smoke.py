"""冒烟测试：确认最小图能跑、能出结构化结果（零 API Key）。"""
from impad.hello_graph import graph


def test_hello_graph_runs():
    out = graph.invoke({"post": {"text": "亲测无限回购，链接在评论区", "blogger": "x"}})
    assert out.get("verdict") in {"明广", "暗广", "非广"}
    assert "report" in out and out["report"]
