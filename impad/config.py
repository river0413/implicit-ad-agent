"""集中读取 .env 配置。其他模块统一从这里取值，避免 os.getenv 散落各处。"""
from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()  # 读取项目根目录的 .env（若存在）


@dataclass
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    langsmith_project: str = os.getenv("LANGSMITH_PROJECT", "implicit-ad-agent")


settings = Settings()
