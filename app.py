"""FastAPI 封装：POST /analyze 传入一条帖子 → 返回结构化审查结果。

本地启动：
    uvicorn app:app --reload
然后浏览器打开 http://127.0.0.1:8000/docs 直接在网页上试。
注意：/analyze 用的是 LLM 图（graph.py），需先配好 .env。
（想零成本先跑通，把下面 import 改成 impad.hello_graph 即可。）
"""
from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from impad.graph import graph

app = FastAPI(title="隐性广告识别 · 起步骨架")


class PostIn(BaseModel):
    text: str
    blogger: str = "未知"
    image_url: str | None = None
    comments: list[str] = []


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(post: PostIn):
    result = graph.invoke({"post": post.model_dump()})
    return {
        "verdict": result.get("verdict"),
        "confidence": result.get("confidence"),
        "evidence": result.get("evidence"),
        "report": result.get("report"),
    }
