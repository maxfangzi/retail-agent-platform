# -*- coding: utf-8 -*-
"""真机自检：全链路验证（需要网络 + .env 里的 MISTRAL_API_KEY）。

依次验证:
  1. /health          服务与工具来源
  2. /rag/ask         RAG 带出处回答
  3. /agent/chat 客服路由  查真实订单（route=service, MCP 工具）
  4. /agent/chat 分析路由  NL→SQL→洞察（route=analytics，SQL 真实跑过）
  5. /agent/chat→/agent/review  退款 HITL：interrupt→批准→恢复

用法:  python scripts/verify_live.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app as fastapi_app  # noqa: E402

OK, FAIL = "✅", "❌"
results = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append(cond)
    print(f"{OK if cond else FAIL} {name}" + (f"  {detail}" if detail else ""))


def main() -> None:
    with TestClient(fastapi_app) as c:
        # 1 health
        h = c.get("/health").json()
        check("health", h.get("status") == "ok", f"tool_source={h.get('agent_tool_source')}")

        # 2 RAG
        r = c.post("/rag/ask", json={"question": "退款政策是什么？"})
        body = r.json()
        check("RAG 带出处", r.status_code == 200 and body.get("sources"), 
              f"来源 {sorted({s['file'] for s in body.get('sources', [])})}")

        # 3 客服路由：真实订单查询
        r = c.post("/agent/chat", json={
            "message": "订单 2e7a8482f6fb09756ca50c10d7bfc047 是什么时候买的？现在什么状态？",
            "thread_id": "live-1"})
        b = r.json()
        check("客服路由 + 真实订单", r.status_code == 200 and b.get("route") == "service",
              f"reply={b.get('reply', '')[:60]}")

        # 4 分析路由：NL→SQL
        r = c.post("/agent/chat", json={
            "message": "GMV 最高的 3 个品类是哪些？各自多少金额？",
            "thread_id": "live-2"})
        b = r.json()
        reply = b.get("reply", "")
        check("分析路由 + 真实SQL", r.status_code == 200 and b.get("route") == "analytics",
              f"reply={reply[:80]}")
        check("分析给到数字", any(ch.isdigit() for ch in reply), "")

        # 5 HITL 退款
        import json as _json
        from app.agent.analytics import run_readonly_sql
        order = run_readonly_sql(
            "SELECT order_id FROM olist_orders WHERE order_status='shipped' "
            "ORDER BY order_estimated_delivery_date LIMIT 1")["rows"][0]["order_id"]
        r = c.post("/agent/chat", json={
            "message": f"订单 {order} 超期未送达，我要退款",
            "thread_id": "live-3"})
        b = r.json()
        check("退款触发人工审核", bool(b.get("pending_review")), 
              f"pending={_json.dumps(b.get('pending_review'), ensure_ascii=False)[:80]}")
        if b.get("pending_review"):
            r2 = c.post("/agent/review", json={"thread_id": "live-3", "approved": True, "note": "自检批准"})
            b2 = r2.json()
            check("批准后恢复", r2.status_code == 200 and "驳回" not in b2.get("reply", ""),
                  f"reply={b2.get('reply', '')[:60]}")

    n_pass = sum(results)
    print(f"\n{n_pass}/{len(results)} 通过" + ("  🎉 全链路 OK" if n_pass == len(results) else "  ⚠️ 有失败项"))
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
