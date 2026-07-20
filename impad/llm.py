"""
厂商无关的 LLM 客户端：走 OpenAI 兼容端点。

改 .env 里的 OPENAI_BASE_URL / LLM_MODEL 就能在 DeepSeek / 通义千问 / OpenAI 间切换，
代码不用动。
"""
from __future__ import annotations
from langchain_openai import ChatOpenAI
from .config import settings


def get_llm(temperature: float = 0.0, max_tokens: int = 4096) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
    )
