"""视觉专家智能体：物体检测 + OCR 文字识别 + 焦点分析。

P2 能力（移植自桌面平行实现 pics/）：
- OCR 把配图里的文字抠出来——暗广常把广告词印在图上，文本专家看不到；
  抠出的文字回灌关键词规则（复用 tools/keywords），命中即形成视觉侧证据。
- 物体检测 + 加权焦点：识别图里拍了什么、视觉重心在哪，作为导购场景的弱信号。

降级（ADR-008）：未安装视觉依赖时投 confidence=0 空票（Judge 忽略），全图零成本可跑；
判定逻辑 vote_from_findings 是纯函数，不依赖任何重库，可零依赖单测。
"""
from __future__ import annotations
from ..state import AdCheckState
from ..tools.keywords import (EXPLICIT_AD_MARKERS, SOFT_AD_SIGNALS,
                              compute_keyword_weights, ad_pressure, summarize_weights)


def _image_source(post: dict) -> str | None:
    """取本地图片路径：优先 image_path，其次 image_url（当它是本地路径时）。"""
    return post.get("image_path") or post.get("image_url")


def vote_from_findings(findings: dict) -> dict:
    """由视觉结果（物体/OCR文字/焦点）推出一票。纯函数，无重依赖。

    返回 {verdict, confidence, evidence, keyword_weights, ocr_text}。
    """
    texts = findings.get("texts", [])
    objects = findings.get("objects", [])
    ocr_text = " ".join(t.get("text", "") for t in texts).strip()
    weights = compute_keyword_weights(ocr_text)

    evidence: list[str] = []
    if objects:
        names = list(dict.fromkeys(o.get("class_name", "") for o in objects))
        evidence.append(f"检测到 {len(objects)} 个物体：{', '.join(names[:5])}")
    hint = _commercial(objects)
    if hint:
        evidence.append(f"含带货相关物体：{', '.join(hint)}")
    if ocr_text:
        shown = ocr_text if len(ocr_text) <= 60 else ocr_text[:60] + "…"
        evidence.append(f"图中文字：{shown}")

    # 判定：以 OCR 文字里的广告信号为主，物体/焦点为辅
    explicit = [w for w in EXPLICIT_AD_MARKERS if w in ocr_text]
    soft = [w for w in SOFT_AD_SIGNALS if w in ocr_text]
    pressure = ad_pressure(weights)
    if explicit:
        verdict, conf = "明广", 0.85
        evidence.append(f"图中文字命中明广标识：{', '.join(explicit)}")
    elif soft or (pressure >= 0.5 and pressure > weights["natural_expression"]):
        verdict, conf = "暗广", round(min(0.55 + 0.1 * len(soft) + pressure * 0.2, 0.85), 2)
        why = f"命中软广词：{', '.join(soft)}" if soft else f"导购压力偏高（{pressure:.2f}）"
        evidence.append(f"图中文字{why}")
    elif hint:
        # 无广告文字但画面聚焦商品：给一个低置信的暗广倾向
        verdict, conf = "暗广", 0.35
        evidence.append("无广告文字，但画面含商品，弱导购信号")
    else:
        verdict, conf = "非广", 0.4
        evidence.append("图中未见明显广告文字或商品")

    if any(v > 0 for v in weights.values()):
        evidence.append(f"图文特征 → {summarize_weights(weights)}")
    return {"verdict": verdict, "confidence": conf, "evidence": evidence,
            "keyword_weights": weights, "ocr_text": ocr_text}


def _commercial(objects: list[dict]) -> list[str]:
    """带货相关物体（薄封装 tools.vision.commercial_objects，避免测试强依赖重库）。"""
    try:
        from ..tools.vision import commercial_objects
        return commercial_objects(objects)
    except Exception:
        return []


def _placeholder_vote(reason: str) -> dict:
    return {"verdict": "非广", "confidence": 0.0, "evidence": [reason]}


def vision_agent(state: AdCheckState) -> AdCheckState:
    post = state.get("post", {})
    src = _image_source(post)
    findings: dict = {}

    if not src:
        vote = _placeholder_vote("未提供图片，视觉专家跳过")
        source = "占位·无图"
    else:
        from ..tools.vision import vision_available
        if not vision_available():
            vote = _placeholder_vote(f"收到图片 {src}，但未安装视觉依赖，降级跳过（本轮不投票）")
            source = "降级·缺依赖"
        else:
            try:
                from ..tools.vision import analyze_image
                findings = analyze_image(str(src))
                vote = vote_from_findings(findings)
                source = "视觉分析"
            except FileNotFoundError:
                vote = _placeholder_vote(f"图片不存在：{src}，视觉专家跳过")
                source = "占位·文件缺失"
            except Exception as e:  # 模型/推理异常不应拖垮全图
                vote = _placeholder_vote(f"视觉分析失败（{type(e).__name__}），降级跳过")
                source = "降级·异常"

    out: AdCheckState = {
        "agent_votes": {**state.get("agent_votes", {}), "vision": vote},
        "evidence": state.get("evidence", []) + [f"[视觉·{source}] {e}" for e in vote["evidence"]],
        "plan": [a for a in state.get("plan", []) if a != "vision"],
    }
    if findings:
        out["vision_findings"] = findings
    return out
