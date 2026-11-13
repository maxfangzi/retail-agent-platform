# -*- coding: utf-8 -*-
"""Supervisor 路由单测：假 LLM/假子图，全离线。"""
import pytest

from app.agent.supervisor import (
    RouteDecision,
    _keyword_route,
    build_supervisor,
)


# ---- 假 router LLM：with_structured_output(...).ainvoke 固定返回决策 ----
class _StubChain:
    def __init__(self, decision, error=None):
        self._decision = decision
        self._error = error

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return RouteDecision(route=self._decision)


class _StubRouterLLM:
    def __init__(self, decision, error=None):
        self._decision = decision
        self._error = error
        self.calls = 0

    def with_structured_output(self, schema):
        self.calls += 1
        return _StubChain(self._decision, self._error)


# ---- 假子图：记录调用并返回固定形状的结果 ----
class _FakeApp:
    def __init__(self, reply, interrupt_value=None):
        self.reply = reply
        self.interrupt_value = interrupt_value
        self.invoked_with = []

    async def ainvoke(self, messages, config):
        self.invoked_with.append((messages, config))
        out = {"messages": [{"role": "assistant", "content": self.reply}]}
        if self.interrupt_value is not None:
            out["__interrupt__"] = [type("I", (), {"value": self.interrupt_value})()]
        return out


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _content(msg) -> str:
    return msg["content"] if isinstance(msg, dict) else msg.content


async def _chat(supervisor, message, thread_id="t1"):
    return await supervisor.ainvoke(
        {"messages": [{"role": "user", "content": message}], "thread_id": thread_id,
         "route": "", "pending": None},
        {"configurable": {"thread_id": thread_id}},
    )


class TestRouting:
    def test_routes_to_service(self):
        service = _FakeApp("客服回复")
        sup = build_supervisor(
            service_app_factory=_async(service),
            analytics_app_factory=_async(_FakeApp("分析回复")),
            router_llm_factory=lambda: _StubRouterLLM("service"),
        )
        state = _run(_chat(sup, "我的订单怎么还没到"))
        assert state["route"] == "service"
        assert _content(state["messages"][-1]) == "客服回复"
        # 子图 thread_id 必须加后缀隔离
        _, cfg = service.invoked_with[0]
        assert cfg["configurable"]["thread_id"] == "t1:service"

    def test_routes_to_analytics(self):
        analytics = _FakeApp("分析回复")
        sup = build_supervisor(
            service_app_factory=_async(_FakeApp("客服回复")),
            analytics_app_factory=_async(analytics),
            router_llm_factory=lambda: _StubRouterLLM("analytics"),
        )
        state = _run(_chat(sup, "上个月销量 top5 品类"))
        assert state["route"] == "analytics"
        _, cfg = analytics.invoked_with[0]
        assert cfg["configurable"]["thread_id"] == "t1:analytics"

    def test_llm_failure_falls_back_to_keywords(self):
        analytics = _FakeApp("分析回复")
        sup = build_supervisor(
            service_app_factory=_async(_FakeApp("客服回复")),
            analytics_app_factory=_async(analytics),
            router_llm_factory=lambda: _StubRouterLLM(None, error=RuntimeError("网络挂了")),
        )
        state = _run(_chat(sup, "帮我看下 GMV 趋势"))
        assert state["route"] == "analytics"

    def test_invalid_llm_output_defaults_to_service(self):
        sup = build_supervisor(
            service_app_factory=_async(_FakeApp("客服回复")),
            analytics_app_factory=_async(_FakeApp("分析回复")),
            router_llm_factory=lambda: _StubRouterLLM("什么乱七八糟"),
        )
        state = _run(_chat(sup, "退款"))
        assert state["route"] == "service"

    def test_interrupt_payload_surfaces_as_pending(self):
        ticket = {"action": "approve_refund", "order_id": "x", "amount_brl": 10}
        service = _FakeApp("", interrupt_value=ticket)
        sup = build_supervisor(
            service_app_factory=_async(service),
            analytics_app_factory=_async(_FakeApp("分析回复")),
            router_llm_factory=lambda: _StubRouterLLM("service"),
        )
        state = _run(_chat(sup, "订单 x 超期了要退款"))
        assert state["pending"] == ticket
        assert "待人工审核" in _content(state["messages"][-1])


class TestKeywordFallback:
    @pytest.mark.parametrize("text,expected", [
        ("订单 123 还没发货", "service"),
        ("退款政策是什么", "service"),
        ("我要投诉快递", "service"),
        ("哪个品类卖得最好", "analytics"),
        ("统计一下每月GMV", "analytics"),
        ("今天天气不错", "service"),  # 默认客服
    ])
    def test_keyword_route(self, text, expected):
        assert _keyword_route(text) == expected


def _async(app):
    async def factory():
        return app
    return factory
