# -*- coding: utf-8 -*-
"""冒烟测试：验证 M0 数据层工具能查到真实订单。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.odata import is_late, query_order, query_order_items, query_order_payment

import sqlite3

conn = sqlite3.connect("data/agent_platform.db")
oid = conn.execute(
    "SELECT order_id FROM olist_orders WHERE order_status='shipped' LIMIT 1"
).fetchone()[0]
print("样本订单:", oid)
print(json.dumps(query_order(oid), ensure_ascii=False, indent=1))
print(json.dumps(query_order_items(oid), ensure_ascii=False, indent=1))
print(json.dumps(query_order_payment(oid), ensure_ascii=False, indent=1))
print(json.dumps(is_late(oid), ensure_ascii=False, indent=1))
print(json.dumps(query_order("nonexistent-123"), ensure_ascii=False, indent=1))
print("SMOKE-OK")
