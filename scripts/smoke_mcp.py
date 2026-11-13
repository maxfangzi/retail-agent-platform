# -*- coding: utf-8 -*-
"""MCP Server 冒烟测试：起 stdio 子进程，走 MCP 协议 list_tools + call_tool。

运行: .venv\\Scripts\\python.exe scripts\\smoke_mcp.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SERVER_CMD = [sys.executable, "-m", "app.mcp.server"]


async def main() -> None:
    params = StdioServerParameters(command=SERVER_CMD[0], args=SERVER_CMD[1:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("MCP tools:", names)
            assert len(names) == 5, f"期望5个工具，实际{len(names)}"

            # 拿一个真实订单号调用一次
            from sqlalchemy import create_engine, text

            from app.core.config import settings

            engine = create_engine(settings.database_url)
            with engine.connect() as conn:
                oid = conn.execute(
                    text("SELECT order_id FROM olist_orders LIMIT 1")
                ).scalar()
            res = await session.call_tool("lookup_order", {"order_id": oid})
            data = res.structuredContent or {}
            if not data:  # 兼容未启用结构化输出的服务端：从文本内容解析
                import json

                data = json.loads(res.content[0].text)
            print("call lookup_order:", {"ok": data.get("ok"), "status": data.get("status")})
            assert data.get("ok") is True
    print("MCP smoke PASS")


if __name__ == "__main__":
    asyncio.run(main())
