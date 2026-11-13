# -*- coding: utf-8 -*-
"""FastAPI 服务入口。

路由:
  GET  /health          健康检查（含依赖就绪状态）
  POST /rag/ask         RAG 知识库客服问答
  POST /agent/chat      LangGraph 智能体对话（M2 实现）
  POST /agent/review    人工审批：批准/驳回 Agent 发起的退款工单（human-in-the-loop）
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.agent.graph import tool_source
from app.agent.supervisor import get_supervisor, resume_service, _text_of
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
        "agent_tool_source": tool_source(),
    }


@app.post("/rag/ask", response_model=AskOut)
def rag_ask(body: AskIn) -> AskOut:
    """知识库客服问答：检索政策文档 + LLM 生成，带出处引用。入口先过防护层。"""
    injected, hit = detect_injection(body.question)
    if injected:
        raise HTTPException(status_code=400, detail="消息包含疑似注入内容，已拦截")
    result = rag_service.answer(mask_pii(body.question))
    return AskOut(answer=result["answer"], sources=result.get("sources", []))


# ---------------- LangGraph Agent（带 human-in-the-loop）----------------

class AgentChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000, examples=["订单 99a478866da877444aa38b616f029de8 还没收到，我要退款"])
    thread_id: str = Field(min_length=1, max_length=64, examples=["customer-1001"])


class AgentReviewIn(BaseModel):
    thread_id: str
    approved: bool
    note: str = ""


async def _run_agent(message: str, thread_id: str):
    """跑一轮 Supervisor 多 Agent 路由（客服/分析）。返回 (回复文本, 路由, 待审批payload或None)。"""
    sup = await get_supervisor()
    cfg = {"configurable": {"thread_id": thread_id}}
    state = await sup.ainvoke(
        {"messages": [{"role": "user", "content": message}],
         "thread_id": thread_id, "route": "", "pending": None},
        cfg,
    )
    return _text_of(state["messages"][-1]), state["route"], state.get("pending")


@app.post("/agent/chat")
async def agent_chat(body: AgentChatIn) -> dict:
    """Agent 对话。若触发退款等敏感操作，返回 pending_review 让人工处理。"""
    injected, _ = detect_injection(body.message)
    if injected:
        raise HTTPException(status_code=400, detail="消息包含疑似注入内容，已拦截")
    reply, route, pending = await _run_agent(mask_pii(body.message), body.thread_id)
    return {"reply": reply, "pending_review": pending, "thread_id": body.thread_id,
            "route": route, "tool_source": tool_source()}


@app.post("/agent/review")
async def agent_review(body: AgentReviewIn) -> dict:
    """人工审批接口：恢复客服子图被 interrupt 暂停的会话（supervisor 线程后缀 :service）。"""
    state = await resume_service(body.thread_id, body.approved, body.note)
    interrupts = state.get("__interrupt__") or []
    if interrupts:
        return {"reply": "仍有待审批事项。", "pending_review": interrupts[0].value}
    return {"reply": state["messages"][-1].content, "pending_review": None}
