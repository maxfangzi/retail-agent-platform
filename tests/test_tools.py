# -*- coding: utf-8 -*-
"""订单工具层单元测试（真实 SQLite 数据，离线可跑）。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.odata import (  # noqa: E402
    is_late, query_order, query_order_items, query_order_payment, query_order_review,
)

_conn = sqlite3.connect(Path(__file__).resolve().parents[1] / "data" / "agent_platform.db")


def _any_order(where: str = "1=1") -> str:
    row = _conn.execute(f"SELECT order_id FROM olist_orders WHERE {where} LIMIT 1").fetchone()
    assert row, "数据库为空？先运行 scripts/seed_db.py"
    return row[0]


def test_query_order_found():
    r = query_order(_any_order())
    assert r["ok"] and r["status"] in {"created", "approved", "invoiced", "shipped", "delivered", "canceled", "unavailable"}


def test_query_order_not_found():
    r = query_order("no-such-order")
    assert not r["ok"] and r["error"] == "order_not_found"


def test_query_order_items():
    r = query_order_items(_any_order("order_status='delivered'"))
    assert r["ok"] and r["items"] and r["total_brl"] > 0


def test_query_payment():
    r = query_order_payment(_any_order())
    assert r["ok"] and r["payments"][0]["type"] in {"credit_card", "boleto", "debit_card", "voucher"}


def test_review_optional():
    r = query_order_review(_any_order())
    assert r["ok"] and isinstance(r["reviews"], list)


def test_is_late_shape():
    r = is_late(_any_order())
    assert r["ok"] and isinstance(r["late"], bool)
