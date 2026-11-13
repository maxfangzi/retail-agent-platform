# -*- coding: utf-8 -*-
"""FastAPI 服务入口。

路由:
  GET  /health          健康检查（含依赖就绪状态）
  POST /rag/ask         RAG 知识库客服问答
  POST /agent/chat      LangGraph 智能体对话（M2 实现）
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.guardrails.pii import detect_injection, mask_pii
from app.rag import service as rag_service

app = FastAPI(
    title="Retail Agent Platform",
    description="零售电商智能运营 Agent 平台：RAG 客服 + LangGraph 智能体",
    version="0.1.0",
)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000, examples=["超过预计送达时间还没收到货怎么办？"])


class AskOut(BaseModel):
    answer: str
    sources: list[dict] = []


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": bool(settings.mistral_api_key),
        "tracing": "langfuse" if settings.langfuse_public_key else "off",
    }


@app.post("/rag/ask", response_model=AskOut)
def rag_ask(body: AskIn) -> AskOut:
    """知识库客服问答：检索政策文档 + LLM 生成，带出处引用。入口先过防护层。"""
    injected, hit = detect_injection(body.question)
    if injected:
        raise HTTPException(status_code=400, detail="消息包含疑似注入内容，已拦截")
    result = rag_service.answer(mask_pii(body.question))
    return AskOut(answer=result["answer"], sources=result.get("sources", []))
