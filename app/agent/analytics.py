# -*- coding: utf-8 -*-
"""运营分析 Agent：自然语言 -> 只读 SQL -> 经营洞察。

与客服 Agent 的区别：客服面向消费者（查单、退款、政策问答），
分析 Agent 面向运营人员（月销量、品类分布、差评率等经营指标），
直接生成 SQL 跑在真实 Olist 数据上，再用人话总结。

安全：SQL 只读守卫（只允许单条 SELECT，自动 LIMIT，黑名单关键字），
并只连业务库账号同等权限的只读连接。
"""
import re
import time
from typing import Any

from langchain_core.tools import tool
from langchain_mistralai import ChatMistralAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition

from app.core.config import settings
from app.tools.odata import _engine  # 复用同一个 SQLite 连接池（只读守卫在 SQL 层做）

# 业务表结构速查（喂给 LLM 生成 SQL 用；真实 schema 的白名单摘要）
SCHEMA_DOC = """\
SQLite 数据库表（Olist 巴西电商真实数据，99441 笔订单）:
- olist_orders(order_id TEXT PK, customer_id TEXT, order_status TEXT  -- delivered/shipped/canceled/...
  , order_purchase_timestamp TEXT  -- 下单时间 'YYYY-MM-DD HH:MM:SS'
  , order_approved_at TEXT, order_delivered_carrier_date TEXT
  , order_delivered_customer_date TEXT  -- 实际送达
  , order_estimated_delivery_date TEXT)  -- 预计送达
- olist_order_items(order_id TEXT, order_item_id INT, product_id TEXT, seller_id TEXT
  , shipping_limit_date TEXT, price REAL, freight_value REAL)  -- 一单多行
- olist_order_payments(order_id TEXT, payment_sequential INT, payment_type TEXT
  -- credit_card/boleto/voucher/debit_card, payment_installments INT, payment_value REAL)
- olist_order_reviews(review_id TEXT PK, order_id TEXT, review_score INT  -- 1~5
  , review_comment_title TEXT, review_comment_message TEXT)
- olist_products(product_id TEXT PK, product_category_name TEXT, product_weight_g REAL
  , product_photos_qty INT)
- category_translation(product_category_name TEXT, product_category_name_english TEXT)  -- 注意表名没有 olist_ 前缀
注意: 日期是 TEXT，比较时用字符串或 date(x)；中文回答时把品类英文名翻译成中文。"""

ANALYST_PROMPT = """你是零售电商的资深运营分析师。把用户的业务问题转成 SQLite 只读 SQL 查询真实数据，
拿到结果后用中文给出经营洞察。

规则：
1. 只能生成 SELECT 语句；结果集默认 LIMIT 50。
2. 先想清楚指标口径（比如"月销量"按 order_purchase_timestamp 的月份、按 order_items 行数或金额），必要时在回答里说明口径。
3. 回答结构：一句话结论 -> 关键数字（表格或列表）-> 1-2 条可执行建议。
4. 数字要忠于查询结果，不要编造；查询失败就说明原因并给出修正后的查询。
"""

_SQL_DENY = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\s*;?\s*$", re.IGNORECASE)


def sanitize_sql(sql: str) -> str:
    """只读守卫：剥注释、禁多语句、禁写关键字、补 LIMIT。返回可执行 SQL 或抛 ValueError。"""
    # 去掉注释，防止把恶意语句藏进注释
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise ValueError("空 SQL")
    if ";" in sql:
        raise ValueError("只允许单条语句")
    if not re.match(r"(?is)^\s*select\b", sql):
        raise ValueError("只允许 SELECT 查询")
    if _SQL_DENY.search(sql):
        raise ValueError("检测到禁止的关键字（只读模式）")
    if not _LIMIT_RE.search(sql):
        sql += " LIMIT 50"
    return sql


def run_readonly_sql(sql: str) -> dict[str, Any]:
    """执行守卫后的 SQL，返回 {"ok", "columns", "rows", "elapsed_ms"}。"""
    try:
        sql = sanitize_sql(sql)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    t0 = time.perf_counter()
    try:
        import pandas as pd

        df = pd.read_sql_query(sql, _engine)
        rows = df.head(50).to_dict(orient="records")
        return {
            "ok": True,
            "columns": list(df.columns),
            "rows": rows,
            "row_count": len(df),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    except Exception as e:  # SQL 语法/列名错误等，回给 LLM 自我修正
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@tool
def execute_readonly_sql(sql: str) -> dict:
    """对零售业务数据库执行一条只读 SQL 查询并返回结果（自动 LIMIT 50）。

    参数 sql: 单条 SQLite SELECT 语句。禁止写操作；结果超 50 行会被截断。
    """
    return run_readonly_sql(sql)


def build_analytics_graph():
    """分析 Agent 图：单工具（execute_readonly_sql）循环，LLM 自我修正 SQL。"""
    llm = ChatMistralAI(
        model=settings.llm_model_fast,
        temperature=0.2,
        api_key=settings.mistral_api_key or "unset",
    )
    llm_with_tools = llm.bind_tools([execute_readonly_sql])
    tool_node = ToolNode([execute_readonly_sql])

    async def analyst_node(state: MessagesState) -> dict:
        msgs = (
            [{"role": "system", "content": ANALYST_PROMPT + "\n\n" + SCHEMA_DOC}]
            + state["messages"]
        )
        return {"messages": [await llm_with_tools.ainvoke(msgs)]}

    g = StateGraph(MessagesState)
    g.add_node("analyst", analyst_node)
    g.add_node("tools", tool_node)  # 名字必须是 tools：tools_condition 的默认路由
    g.add_edge(START, "analyst")
    g.add_conditional_edges("analyst", tools_condition)
    g.add_edge("tools", "analyst")
    return g.compile(checkpointer=InMemorySaver())
