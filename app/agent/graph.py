# -*- coding: utf-8 -*-
"""LangGraph 智能体：客服 Agent 的"大脑"。

架构（面试重点讲这张图）:
  用户消息 → [guardrails 入口检查] → [agent 节点: Mistral 函数调用循环]
           → [tool 节点: 执行订单查询/退款登记] → 回到 agent → 最终回复

企业级要素:
- 退款登记(create_refund_ticket)是敏感操作：执行前 interrupt() 暂停，
  等人工通过 API 批准/驳回后才继续 —— human-in-the-loop；
- 所有工具只读或"写待审核队列"，Agent 无权直接改库 —— 最小权限原则。
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langchain_core.tools import tool
from langchain_mistralai import ChatMistralAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt

from app.core.config import settings
from app.tools import odata

TICKET_DIR = Path(__file__).resolve().parents[2] / "data" / "review_queue"


# ---------------- 工具定义（docstring 就是给模型看的说明书）----------------

@tool
def lookup_order(order_id: str) -> dict:
    """按订单号查询订单状态、购买时间、预计送达与实际送达时间。"""
    return odata.query_order(order_id)


@tool
def lookup_order_items(order_id: str) -> dict:
    """查询订单里买了什么：商品类目、单价、运费、合计金额。"""
    return odata.query_order_items(order_id)


@tool
def lookup_order_payment(order_id: str) -> dict:
    """查询订单的支付方式、分期与支付金额。"""
    return odata.query_order_payment(order_id)


@tool
def lookup_order_review(order_id: str) -> dict:
    """查询客户对该订单的评价（1-5星及内容），处理投诉前先看。"""
    return odata.query_order_review(order_id)


@tool
def check_delivery_late(order_id: str) -> dict:
    """判断订单是否超过预计送达日期仍未送达，返回是否超期和超期天数。"""
    return odata.is_late(order_id)


@tool
def create_refund_ticket(order_id: str, reason: str, amount_brl: float) -> dict:
    """登记一笔退款待审核工单。注意：这是敏感操作，需要人工审核后才生效。"""
    TICKET_DIR.mkdir(parents=True, exist_ok=True)
    decision = interrupt({  # 图在这里暂停，等人批
        "action": "approve_refund",
        "order_id": order_id, "reason": reason, "amount_brl": amount_brl,
    })
    approved = bool(decision.get("approved"))
    ticket = {
        "order_id": order_id, "reason": reason, "amount_brl": amount_brl,
        "approved": approved, "reviewer_note": decision.get("note", ""),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = TICKET_DIR / f"{order_id}_{int(time.time())}.json"
    path.write_text(json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "ticket_file": path.name, "approved": approved,
            "message": "退款工单已登记并通过审核" if approved else "退款申请已被人工驳回"}


ALL_TOOLS = [lookup_order, lookup_order_items, lookup_order_payment,
             lookup_order_review, check_delivery_late, create_refund_ticket]

SYSTEM_PROMPT = """你是电商平台"智购"的售后客服 Agent。工作守则：
1. 客户问题涉及具体订单时，先调用工具查真实数据再回答，绝不编造订单状态或金额。
2. 客户没有给订单号时，礼貌地请客户提供订单号（格式是32位字母数字）。
3. 政策类问题（配送时效、退款条件、支付方式）依据你已知的平台政策回答，不确定就转人工。
4. 只有客户明确要求退款且你已核实订单信息后，才调用 create_refund_ticket 登记工单。
5. 回答礼貌、简洁、专业，用客户提问的语言回复。"""


def build_graph(tools: list):
    """构建客服 Agent 图（工具从外部传入）。返回编译好的 (app, checkpointer)。

    async 设计：MCP 适配器工具只支持异步调用，图节点和调用方全程 async。
    """
    llm = ChatMistralAI(
        model=settings.llm_model_fast,
        temperature=0.2,
        api_key=settings.mistral_api_key or "unset",
    )
    llm_with_tools = llm.bind_tools(tools)
    tool_node = ToolNode(tools)

    async def agent_node(state: MessagesState) -> dict:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + state["messages"]
        return {"messages": [await llm_with_tools.ainvoke(msgs)]}

    g = StateGraph(MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)  # 有工具调用→tools，否则→END
    g.add_edge("tools", "agent")                        # 工具结果回给 agent 继续
    checkpointer = InMemorySaver()  # 生产换 SqliteSaver/Postgres，支持断点恢复
    return g.compile(checkpointer=checkpointer), checkpointer


# ---------------- 工具来源：优先 MCP，失败降级为进程内直连 ----------------

_app = None
_checkpointer: InMemorySaver | None = None
_tool_source = "unset"


def _direct_data_tools() -> list:
    """进程内直连工具（MCP 不可用时的降级路径，同一份 odata 实现）。"""
    return [
        tool(odata.query_order, name="lookup_order", description="按订单号查询订单状态、购买时间、预计送达与实际送达时间。"),
        tool(odata.query_order_items, name="lookup_order_items", description="查询订单里买了什么：商品类目、单价、运费、合计金额。"),
        tool(odata.query_order_payment, name="lookup_order_payment", description="查询订单的支付方式、分期与支付金额。"),
        tool(odata.query_order_review, name="lookup_order_review", description="查询客户对该订单的评价（1-5星及内容），处理投诉前先看。"),
        tool(odata.is_late, name="check_delivery_late", description="判断订单是否超过预计送达日期仍未送达，返回是否超期和超期天数。"),
    ]


async def _load_data_tools() -> list:
    """优先走 MCP 协议加载工具（app/mcp/server.py），失败则降级直连。"""
    global _tool_source
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({
            "retail-order-data": {
                "command": sys.executable,
                "args": ["-m", "app.mcp.server"],
                "transport": "stdio",
            }
        })
        tools = await client.get_tools()
        _tool_source = "mcp"
        return tools
    except Exception as e:  # MCP 子进程失败不应拖垮主服务
        print(f"[graph] MCP 工具加载失败，降级为进程内直连: {type(e).__name__}: {e}")
        _tool_source = "direct"
        return _direct_data_tools()


async def get_app():
    """惰性构建并缓存 Agent 图（首次调用时加载工具）。"""
    global _app, _checkpointer
    if _app is None:
        data_tools = await _load_data_tools()
        tools = data_tools + [create_refund_ticket]
        _app, _checkpointer = build_graph(tools)
    return _app


def tool_source() -> str:
    return _tool_source
