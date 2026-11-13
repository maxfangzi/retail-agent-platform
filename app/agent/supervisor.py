# -*- coding: utf-8 -*-
"""Supervisor 多 Agent 路由：一个入口，按意图分派给客服 Agent 或运营分析 Agent。

架构（对应 LangGraph Supervisor 模式）:
    START → router（LLM 意图分类，失败降级关键词规则）
         → service_agent  客服子图（查单/退款/HITL，工具经 MCP 加载）
         → analytics_agent 运营分析子图（NL→只读SQL→洞察）

子图各自带独立 checkpointer（thread_id 加后缀隔离会话），
HITL 中断 payload 通过 state["pending"] 透出，由 /agent/review 恢复客服子图。
"""
import re
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langchain_mistralai import ChatMistralAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from app.core.config import settings

# 意图关键词（router LLM 不可用时的降级规则；中文电商语境）
_SERVICE_KW = re.compile(r"订单|退款|退货|发货|物流|快递|签收|取消|评价|投诉|政策|运费|我的|多久")
_ANALYTICS_KW = re.compile(r"销量|销售|gmv|品类|类目|趋势|同比|环比|分析|报表|统计|多少单|转化|客单|top|排行")


class SupervisorState(TypedDict):
    messages: Annotated[list[AnyMessage], lambda a, b: a + b]
    thread_id: str
    route: str
    pending: dict | None


class RouteDecision(BaseModel):
    """router 的结构化输出。"""
    route: str = Field(description="service 或 analytics")


ROUTER_PROMPT = """你是零售平台的流量调度器。判断用户消息该交给哪个 Agent：
- service：消费者客服（查订单、退款退货、物流、支付、政策咨询、投诉）
- analytics：运营/经营分析（销量、GMV、品类分布、趋势、Top 排行、统计报表）
只输出路由结果。"""


def _keyword_route(text: str) -> str:
    """关键词降级路由：分析词命中优先（"销量""GMV"等更稀有），否则默认客服。"""
    if _ANALYTICS_KW.search(text.lower()):
        return "analytics"
    return "service"


def build_router_llm() -> ChatMistralAI:
    return ChatMistralAI(
        model=settings.llm_model_fast,
        temperature=0,
        api_key=settings.mistral_api_key or "unset",
    )


def _text_of(msg) -> str:
    """兼容 dict 消息与 LangChain message 对象。"""
    return msg["content"] if isinstance(msg, dict) else getattr(msg, "content", str(msg))


def build_supervisor(service_app_factory, analytics_app_factory, router_llm_factory=None):
    """组装 Supervisor 图。

    三个 factory 都可注入（测试时传假 LLM/假子图），生产用默认真实现。
    service_app_factory/analytics_app_factory: () -> awaitable 或 同步 返回编译好的子图。
    """
    if router_llm_factory is None:
        router_llm_factory = build_router_llm
    router_llm = router_llm_factory()

    async def router_node(state: SupervisorState) -> dict:
        m = state["messages"][-1] if state["messages"] else None
        text = (m["content"] if isinstance(m, dict) else getattr(m, "content", "")) if m else ""
        try:
            decision = await router_llm.with_structured_output(RouteDecision).ainvoke(
                [{"role": "system", "content": ROUTER_PROMPT},
                 {"role": "user", "content": f"用户消息：{text}"}]
            )
            route = decision.route if decision.route in ("service", "analytics") else "service"
        except Exception as e:  # LLM 挂了也不能没有入口：降级关键词路由
            print(f"[supervisor] router LLM 失败，降级关键词路由: {type(e).__name__}: {e}")
            route = _keyword_route(text)
        return {"route": route}

    async def service_node(state: SupervisorState) -> dict:
        app = await service_app_factory()
        out = await app.ainvoke(
            {"messages": state["messages"]},
            {"configurable": {"thread_id": f"{state['thread_id']}:service"}},
        )
        pending = None
        if out.get("__interrupt__"):
            pending = out["__interrupt__"][0].value
            reply = "【待人工审核】退款工单已提交，等待审批。"
        else:
            reply = _text_of(out["messages"][-1])
        return {"messages": [{"role": "assistant", "content": reply}], "pending": pending}

    async def analytics_node(state: SupervisorState) -> dict:
        app = await analytics_app_factory()
        out = await app.ainvoke(
            {"messages": state["messages"]},
            {"configurable": {"thread_id": f"{state['thread_id']}:analytics"}},
        )
        reply = _text_of(out["messages"][-1])
        return {"messages": [{"role": "assistant", "content": reply}], "pending": None}

    g = StateGraph(SupervisorState)
    g.add_node("router", router_node)
    g.add_node("service_agent", service_node)
    g.add_node("analytics_agent", analytics_node)
    g.add_edge(START, "router")
    g.add_conditional_edges("router", lambda s: s["route"],
                            {"service": "service_agent", "analytics": "analytics_agent"})
    g.add_edge("service_agent", END)
    g.add_edge("analytics_agent", END)
    return g.compile(checkpointer=InMemorySaver())


# ---------------- 生产装配（惰性单例） ----------------

_supervisor = None


async def get_supervisor():
    global _supervisor
    if _supervisor is None:
        from app.agent.analytics import build_analytics_graph
        from app.agent.graph import get_app

        analytics_app_cache = {}

        async def analytics_factory():
            if "app" not in analytics_app_cache:
                analytics_app_cache["app"] = build_analytics_graph()
            return analytics_app_cache["app"]

        _supervisor = build_supervisor(
            service_app_factory=get_app,
            analytics_app_factory=analytics_factory,
        )
    return _supervisor


async def resume_service(thread_id: str, approved: bool, note: str) -> dict:
    """HITL 审批入口：直接恢复客服子图（supervisor 子图线程后缀 :service）。"""
    from langgraph.types import Command

    from app.agent.graph import get_app

    app = await get_app()
    return await app.ainvoke(
        Command(resume={"approved": approved, "note": note}),
        {"configurable": {"thread_id": f"{thread_id}:service"}},
    )
