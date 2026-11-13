# -*- coding: utf-8 -*-
"""全局配置：所有可变参数集中在 .env，代码里只读这里。"""
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings(BaseSettings):
    # --- LLM（Mistral）---
    mistral_api_key: str = ""
    llm_model_premium: str = "mistral-large-latest"
    llm_model_fast: str = "mistral-small-latest"

    # --- RAG ---
    chroma_persist_dir: str = str(BASE_DIR / "chroma_db")
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # --- 数据库 ---
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'agent_platform.db'}"

    # --- Langfuse tracing（留空=关闭）---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # --- 服务 ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    class Config:
        env_file = BASE_DIR / ".env"
        extra = "ignore"


settings = Settings()
