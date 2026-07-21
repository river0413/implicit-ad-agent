"""视觉专家测试：判定纯函数 + 降级路径（不依赖 torch/opencv，全部零 Key）。"""
import impad.tools.vision as vision
from impad.agents.vision_agent import vote_from_findings, vision_agent
from impad.agents import supervisor
from impad.graph import graph
from impad.config import settings


def _findings(ocr_texts=(), objects=()):
    return {
        "objects": [{"class_name": n, "confidence": 0.9, "bbox": [0, 0, 1, 1],
                     "center": [0, 0]} for n in objects],
        "texts": [{"text": t, "confidence": 0.9} for t in ocr_texts],
        "focus": {},
    }


def test_vote_explicit_marker_in_image():
    v = vote_from_findings(_findings(ocr_texts=["扫码领券", "广告"]))
    assert v["verdict"] == "明广"
    assert v["confidence"] >= 0.8


def test_vote_soft_signal_in_image():
    v = vote_from_findings(_findings(ocr_texts=["无限回购", "亲测好用"]))
    assert v["verdict"] == "暗广"


def test_vote_pressure_fallback():
    v = vote_from_findings(_findings(ocr_texts=["限时抢购！扫码下单，爆款种草必买，手慢无"]))
    assert v["verdict"] == "暗广"


def test_vote_commercial_object_weak_hint():
    v = vote_from_findings(_findings(objects=["bottle", "cup"]))
    assert v["verdict"] == "暗广" and v["confidence"] < 0.5  # 弱信号，低置信


def test_vote_clean_image():
    v = vote_from_findings(_findings(objects=["person"], ocr_texts=["今天天气不错"]))
    assert v["verdict"] == "非广"


def test_agent_no_image_placeholder():
    out = vision_agent({"post": {"text": "无图帖"}})
    assert out["agent_votes"]["vision"]["confidence"] == 0.0


def test_agent_degrades_when_deps_missing(monkeypatch):
    monkeypatch.setattr(vision, "vision_available", lambda: False)
    out = vision_agent({"post": {"image_path": "x.jpg"}})
    vote = out["agent_votes"]["vision"]
    assert vote["confidence"] == 0.0
    assert "vision_findings" not in out  # 降级时不写结构化结果
    assert any("降级" in e for e in out["evidence"])


def test_supervisor_schedules_vision_on_image_path():
    assert "vision" in supervisor({"post": {"text": "hi", "image_path": "a.jpg"}})["plan"]


def test_full_graph_with_image_degrades_gracefully(monkeypatch):
    # 缺依赖 + 无 Key：全图仍应跑通，视觉投空票被 Judge 忽略
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(vision, "vision_available", lambda: False)
    out = graph.invoke({"post": {"text": "这支面霜我亲测三个月，无限回购",
                                 "blogger": "x", "image_path": "no_such.jpg"}})
    assert out["verdict"] in {"明广", "暗广", "非广"}
    assert out["agent_votes"]["vision"]["confidence"] == 0.0
    assert out["report"]
