"""6 维关键词权重与其在 NLP/Judge 中的透传测试（全部零 Key）。"""
from impad.tools.keywords import (WEIGHT_DIMENSIONS, compute_keyword_weights,
                                  ad_pressure, summarize_weights)
from impad.agents import nlp_agent, judge
from impad.config import settings


def test_weights_shape_and_range():
    w = compute_keyword_weights("今天去图书馆看书，心情不错")
    assert set(w) == set(WEIGHT_DIMENSIONS)
    assert all(0.0 <= v <= 1.0 for v in w.values())


def test_natural_text_scores_natural_high():
    w = compute_keyword_weights("今天和朋友周末逛街，分享一下心情和生活")
    assert w["natural_expression"] > 0
    assert ad_pressure(w) < w["natural_expression"]


def test_promo_text_has_pressure():
    w = compute_keyword_weights("限时抢购！扫码下单立减，爆款种草必买，手慢无")
    assert ad_pressure(w) >= 0.5
    assert w["natural_expression"] == 0.0
    assert "促销种草" in summarize_weights(w) or "行动召唤" in summarize_weights(w)


def test_summary_empty_when_no_signal():
    assert summarize_weights(compute_keyword_weights("嗯嗯好的")) == "无显著关键词信号"


def test_nlp_vote_carries_weights(monkeypatch):
    # 强制规则降级，避免联网
    monkeypatch.setattr(settings, "openai_api_key", "")
    out = nlp_agent({"post": {"text": "限时抢购！扫码下单立减，爆款种草必买"}})
    assert "keyword_weights" in out
    assert "keyword_weights" in out["agent_votes"]["nlp"]
    assert set(out["keyword_weights"]) == set(WEIGHT_DIMENSIONS)


def test_rule_pressure_fallback_flags_hidden_ad(monkeypatch):
    # 不含明广标识、也不含软广词，仅靠导购压力判暗广
    monkeypatch.setattr(settings, "openai_api_key", "")
    out = nlp_agent({"post": {"text": "限时抢购！扫码下单立减，爆款必买，手慢无"}})
    assert out["agent_votes"]["nlp"]["verdict"] == "暗广"


def test_judge_passes_weights_through():
    out = judge({
        "agent_votes": {"nlp": {"verdict": "暗广", "confidence": 0.8, "evidence": []}},
        "keyword_weights": {d: 0.5 for d in WEIGHT_DIMENSIONS},
    })
    assert out["keyword_weights"]
    assert any("可解释特征" in e for e in out["evidence"])
