# -*- coding: utf-8 -*-
"""M0 数据层：把 Olist 巴西电商真实数据集（10万订单）从 CSV 装进 SQLite。

用法:  python scripts/seed_db.py
产出:  data/agent_platform.db（表结构见 SCHEMA）
设计要点: 日期列统一转 datetime；评论分数/支付方式保留原值，
          中文类目名通过 translation 表连接——为 Agent 工具查询做准备。
"""
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data" / "raw"
DB_URL = f"sqlite:///{BASE / 'data' / 'agent_platform.db'}"

DATE_COLS = {
    "olist_orders_dataset.csv": [
        "order_purchase_timestamp", "order_approved_at",
        "order_delivered_carrier_date", "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "olist_order_reviews_dataset.csv": [
        "review_creation_date", "review_answer_timestamp",
    ],
}


def main() -> None:
    engine = create_engine(DB_URL)
    for csv in sorted(RAW.glob("*.csv")):
        df = pd.read_csv(csv)
        for col in DATE_COLS.get(csv.name, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        table = csv.stem.replace("_dataset", "").replace("product_category_name_translation", "category_translation")
        df.to_sql(table, engine, if_exists="replace", index=False)
        print(f"{table:20s} {len(df):>7,} 行")
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_orders_customer ON olist_orders(customer_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_items_order ON olist_order_items(order_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_reviews_order ON olist_order_reviews(order_id)"))
    print("done ->", DB_URL)


if __name__ == "__main__":
    main()
