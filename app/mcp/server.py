# -*- coding: utf-8 -*-
"""MCP Server：把订单数据工具暴露为标准 MCP (Model Context Protocol) 服务。

为什么用 MCP（面试重点）：
- MCP 是 Anthropic 发起的开放协议，2025 年起成为 LLM 工具生态的事实标准
  （OpenAI/Google/Microsoft 均已宣布支持）。工具写成 MCP Server 后，
  任何 MCP 客户端（Claude Desktop、Cursor、其他 Agent）都能直接复用，
  不再绑死在本项目的 LangGraph 里。
- 本 Server 复用 app/tools/odata.py 的同一套只读函数——单一事实源，
  LangGraph 直连和 MCP 两种接入方式共享同一份工具实现。

运行: .venv\\Scripts\\python.exe -m app.mcp.server   （stdio 传输）
验证: python scripts/smoke_mcp.py
"""
from mcp.server.fastmcp import FastMCP

from app.tools import odata

mcp = FastMCP(
    "retail-order-data",
    instructions=(
        "零售电商订单数据只读查询服务（Olist 真实数据集）。"
        "所有工具只读，不提供任何写操作。"
    ),
)


@mcp.tool()
def lookup_order(order_id: str) -> dict:
    """按订单号查询订单状态、购买时间、预计送达与实际送达时间。"""
    return odata.query_order(order_id)


@mcp.tool()
def lookup_order_items(order_id: str) -> dict:
    """查询订单里买了什么：商品类目、单价、运费、合计金额。"""
    return odata.query_order_items(order_id)


@mcp.tool()
def lookup_order_payment(order_id: str) -> dict:
    """查询订单的支付方式、分期与支付金额。"""
    return odata.query_order_payment(order_id)


@mcp.tool()
def lookup_order_review(order_id: str) -> dict:
    """查询客户对该订单的评价（1-5星及内容），处理投诉前先看。"""
    return odata.query_order_review(order_id)


@mcp.tool()
def check_delivery_late(order_id: str) -> dict:
    """判断订单是否超过预计送达日期仍未送达，返回是否超期和超期天数。"""
    return odata.is_late(order_id)


if __name__ == "__main__":
    mcp.run()  # stdio 传输：适合与 Agent 同机编排（docker compose 里加一个 service 即可）
