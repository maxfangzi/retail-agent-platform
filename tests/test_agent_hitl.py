# -*- coding: utf-8 -*-
"""Human-in-the-loop 离线测试：用假 LLM 驱动退款 interrupt/resume 全流程。

不调真实 API：agent 节点用的模型被替换为带工具调用的假模型，验证
LangGraph interrupt() 暂停 → Command(resume) 恢复 → 工单落盘 的完整闭环。
"""
import json
from pathlib import Path

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

import app.agent.graph as graph_mod

TICKET_DIR: Path = graph_mod.TICKET_DIR


@pytest.fixture()
def clean_tickets():
    """每个测试前清空工单目录，保证断言只看到本测试产生的工单。"""
    TICKET_DIR.mkdir(parents=True, exist_ok=True)
    for f in TICKET_DIR.glob("*.json"):
        f.unlink()
    yield TICKET_DIR


def _fake_graph(text_after_tool: str = "退款工单已处理完毕，请注意查收。"):
    """构造一个"第一次响应发起退款工具调用、第二次响应纯文本"的假 Agent 图。"""
    tool_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "create_refund_ticket",
            "args": {"order_id": "test0001", "reason": "超期未送达", "amount_brl": 99.9},
            "id": "call_1",
        }],
    )
    from langchain_core.prompts import ChatPromptTemplate

    fake = GenericFakeChatModel(messages=iter([tool_call, AIMessage(content=text_after_tool)]))
    tool_node = graph_mod.ToolNode(graph_mod.ALL_TOOLS)

    def agent_node(state):
        msgs = [graph_mod.SYSTEM_PROMPT] + [m.content if isinstance(m, str) else m for m in state["messages"]]
        return {"messages": [fake.invoke(msgs)]}

    g = graph_mod.StateGraph(graph_mod.MessagesState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_edge(graph_mod.START, "agent")
    g.add_conditional_edges("agent", graph_mod.tools_condition)
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=graph_mod.InMemorySaver())


def test_refund_interrupt_and_approve(clean_tickets):
    app = _fake_graph()
    cfg = {"configurable": {"thread_id": "t-test"}}
    state = app.invoke({"messages": [{"role": "user", "content": "我要退款"}]}, cfg)

    # 1) 图必须暂停在 interrupt，且有工单内容透出
    assert state.get("__interrupt__"), "退款工具未被 interrupt 拦下"
    payload = state["__interrupt__"][0].value
    assert payload["order_id"] == "test0001" and payload["amount_brl"] == 99.9
    # 暂停时不应已有工单落盘
    assert not list(TICKET_DIR.glob("test0001_*.json")), "审批前工单就落盘了，human-in-the-loop 失效"

    # 2) 人工批准后恢复，工具执行并写工单
    final = app.invoke(Command(resume={"approved": True, "note": "已核实"}), cfg)
    reply = final["messages"][-1].content
    assert "已处理完毕" in reply
    tickets = list(TICKET_DIR.glob("test0001_*.json"))
    assert len(tickets) == 1, "批准后应有且仅有一张工单"
    ticket = json.loads(tickets[0].read_text(encoding="utf-8"))
    assert ticket["approved"] is True and ticket["order_id"] == "test0001"


def test_refund_reject_writes_rejected_ticket(clean_tickets):
    app = _fake_graph(text_after_tool="非常抱歉，您的退款申请未通过审核。")
    cfg = {"configurable": {"thread_id": "t-reject"}}
    state = app.invoke({"messages": [{"role": "user", "content": "我要退款"}]}, cfg)
    assert state.get("__interrupt__")

    final = app.invoke(Command(resume={"approved": False, "note": "不符合政策"}), cfg)
    tickets = list(TICKET_DIR.glob("test0001_*.json"))
    assert len(tickets) == 1
    ticket = json.loads(tickets[0].read_text(encoding="utf-8"))
    assert ticket["approved"] is False and ticket["reviewer_note"] == "不符合政策"
    assert "未通过" in final["messages"][-1].content
