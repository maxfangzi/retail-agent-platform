# -*- coding: utf-8 -*-
"""订单数据查询工具：Agent 的"手"。

每个函数都是一个 Agent 可调用的工具（MCP 风格：输入输出都是结构化的 dict，
带明确的错误语义）。所有函数只读，绝不写库——Agent 工具的第一安全原则。
"""
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from app.core.config import settings

_engine = create_engine(settings.database_url)


def _q(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with _engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]


def _iso(value: Any) -> str | None:
    return pd.Timestamp(value).isoformat() if pd.notna(value) else None


def query_order(order_id: str) -> dict[str, Any]:
    """按订单号查订单主档：状态、购买时间、预计/实际送达时间。"""
    rows = _q(
        "SELECT order_id, customer_id, order_status, order_purchase_timestamp,"
        " order_approved_at, order_delivered_carrier_date, order_delivered_customer_date,"
        " order_estimated_delivery_date FROM olist_orders WHERE order_id = :oid",
        {"oid": order_id},
    )
    if not rows:
        return {"ok": False, "error": "order_not_found", "message": f"订单 {order_id} 不存在"}
    r = rows[0]
    return {
        "ok": True,
        "order_id": r["order_id"],
        "status": r["order_status"],
        "purchased_at": _iso(r["order_purchase_timestamp"]),
        "delivered_at": _iso(r["order_delivered_customer_date"]),
        "estimated_delivery": _iso(r["order_estimated_delivery_date"]),
    }


def query_order_items(order_id: str) -> dict[str, Any]:
    """查订单商品明细（含中文类目名）：商品、数量、金额。"""
    rows = _q(
        "SELECT i.product_id, t.product_category_name_english AS category,"
        " i.order_item_id AS item_seq, i.price, i.freight_value"
        " FROM olist_order_items i"
        " LEFT JOIN olist_products p ON i.product_id = p.product_id"
        " LEFT JOIN category_translation t ON p.product_category_name = t.product_category_name"
        " WHERE i.order_id = :oid ORDER BY i.order_item_id",
        {"oid": order_id},
    )
    if not rows:
        return {"ok": False, "error": "no_items", "message": f"订单 {order_id} 无商品明细"}
    items = [
        {"seq": r["item_seq"], "category": r["category"] or "unknown",
         "price_brl": float(r["price"]), "freight_brl": float(r["freight_value"])}
        for r in rows
    ]
    return {"ok": True, "order_id": order_id, "items": items,
            "total_brl": round(sum(i["price_brl"] + i["freight_brl"] for i in items), 2)}


def query_order_payment(order_id: str) -> dict[str, Any]:
    """查订单支付方式与金额（一个订单可能多条支付记录）。"""
    rows = _q(
        "SELECT payment_type, payment_installments, payment_value"
        " FROM olist_order_payments WHERE order_id = :oid",
        {"oid": order_id},
    )
    if not rows:
        return {"ok": False, "error": "no_payment", "message": f"订单 {order_id} 无支付记录"}
    return {"ok": True, "order_id": order_id,
            "payments": [{"type": r["payment_type"],
                          "installments": r["payment_installments"],
                          "value_brl": float(r["payment_value"])} for r in rows]}


def query_order_review(order_id: str) -> dict[str, Any]:
    """查订单评价（1-5 分 + 标题/正文，客服需先了解客户不满原因）。"""
    rows = _q(
        "SELECT review_score, review_comment_title, review_comment_message"
        " FROM olist_order_reviews WHERE order_id = :oid",
        {"oid": order_id},
    )
    if not rows:
        return {"ok": True, "order_id": order_id, "reviews": []}
    return {"ok": True, "order_id": order_id,
            "reviews": [{"score": r["review_score"],
                         "title": r["review_comment_title"],
                         "message": r["review_comment_message"]} for r in rows]}


def is_late(order_id: str) -> dict[str, Any]:
    """判断订单是否超期未送达（客服判责的核心依据）。"""
    o = query_order(order_id)
    if not o.get("ok"):
        return o
    if o["delivered_at"]:
        return {"ok": True, "order_id": order_id, "late": False,
                "reason": "already_delivered", "delivered_at": o["delivered_at"]}
    if not o["estimated_delivery"]:
        return {"ok": True, "order_id": order_id, "late": False, "reason": "no_estimate"}
    est = pd.Timestamp(o["estimated_delivery"])
    days_late = (pd.Timestamp.utcnow().tz_localize(None) - est).days
    return {"ok": True, "order_id": order_id, "late": days_late > 0,
            "days_late": max(days_late, 0), "status": o["status"],
            "estimated_delivery": o["estimated_delivery"]}


# ---- 工具注册表：LangGraph Agent 按这个名字映射到函数 ----
TOOLS: dict[str, Any] = {
    "query_order": query_order,
    "query_order_items": query_order_items,
    "query_order_payment": query_order_payment,
    "query_order_review": query_order_review,
    "is_late": is_late,
}
