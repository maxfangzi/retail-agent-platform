# -*- coding: utf-8 -*-
"""全局配置：所有可变参数集中在 .env，代码里只读这里。"""
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# config.py 位于 app/core/ 下，向上三级才是项目根
BASE_DIR = Path(__file__).resolve().parents[2]
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
    # 注意：SQLite URL 必须用正斜杠（Windows 反斜杠 + 中文路径会解析失败）
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'agent_platform.db').as_posix()}"

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
