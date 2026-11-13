# -*- coding: utf-8 -*-
"""零售电商智能运营 Agent 平台 - 演示控制台（Streamlit）。

启动:  streamlit run streamlit_app.py
功能:  智能客服(RAG) / 多Agent路由对话(客服+分析+HITL) / 数据概览(SQL守卫)
全部进程内直连，不需要起 FastAPI。
"""
import asyncio

import streamlit as st

st.set_page_config(page_title="零售 Agent 平台", page_icon="🛒", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []          # (role, text)
if "pending" not in st.session_state:
    st.session_state.pending = None        # 待审批工单
if "thread_id" not in st.session_state:
    st.session_state.thread_id = "streamlit-demo"


def _run(coro):
    return asyncio.run(coro)


@st.cache_resource(show_spinner="加载模型与向量库（首次约 20 秒）…")
def load_rag():
    from app.rag import service as rag_service

    rag_service  # 预热 import；首次 answer 时自动 ingest
    return True


@st.cache_resource(show_spinner="连接 MCP 工具服务…")
def load_supervisor():
    from app.agent.supervisor import get_supervisor

    return _run(get_supervisor())


tab1, tab2, tab3 = st.tabs(["💬 智能客服（RAG）", "🤖 多 Agent 路由对话", "📊 数据概览"])

# ---------------- Tab1: RAG 客服 ----------------
with tab1:
    st.subheader("知识库问答（政策文档检索 + 生成，带出处）")
    load_rag()
    q = st.text_input("问点什么", "超过预计送达时间还没收到货怎么办？", key="rag_q")
    if st.button("提问", key="rag_ask") and q.strip():
        from app.guardrails.pii import detect_injection, mask_pii
        from app.rag import service as rag_service

        if detect_injection(q)[0]:
            st.error("已拦截：消息包含疑似注入内容")
        else:
            with st.spinner("检索 + 生成…"):
                out = rag_service.answer(mask_pii(q))
            st.markdown(out["answer"])
            for s in out.get("sources", []):
                st.caption(f"[来源] {s['file']} · {s.get('section', '')} · 相似度 {s.get('score', '')}")

# ---------------- Tab2: Supervisor 多 Agent ----------------
with tab2:
    st.subheader("一个入口，自动路由到 客服Agent / 运营分析Agent")
    st.caption("客服会查真实 Olist 订单库；分析会把问题转成只读 SQL 跑真实数据；退款会触发人工审批（HITL）。")
    load_supervisor()

    for role, text in st.session_state.history:
        with st.chat_message(role):
            st.markdown(text)

    # 待审批工单卡
    if st.session_state.pending:
        p = st.session_state.pending
        with st.chat_message("assistant"):
            st.warning("⚠️ 退款工单待人工审核")
            st.json(p, expanded=False)
            c1, c2 = st.columns(2)
            if c1.button("✅ 批准退款", key="approve"):
                from app.agent.supervisor import resume_service

                out = _run(resume_service(st.session_state.thread_id, True, "演示批准"))
                st.session_state.pending = None
                st.session_state.history.append(("assistant", out["messages"][-1].content))
                st.rerun()
            if c2.button("❌ 驳回", key="reject"):
                from app.agent.supervisor import resume_service

                out = _run(resume_service(st.session_state.thread_id, False, "演示驳回"))
                st.session_state.pending = None
                st.session_state.history.append(("assistant", out["messages"][-1].content))
                st.rerun()

    msg = st.chat_input("例如：订单 2e7a8482f6fb09756ca50c10d7bfc047 超期了要退款 / 上个月销量最好的3个品类是什么")
    if msg:
        st.session_state.history.append(("user", msg))
        with st.chat_message("user"):
            st.markdown(msg)
        with st.chat_message("assistant"):
            with st.spinner("Supervisor 路由 + Agent 执行…"):
                from app.agent.supervisor import get_supervisor

                sup = load_supervisor()
                state = _run(sup.ainvoke(
                    {"messages": [{"role": "user", "content": msg}],
                     "thread_id": st.session_state.thread_id, "route": "", "pending": None},
                    {"configurable": {"thread_id": st.session_state.thread_id}},
                ))
            badge = "🧭 客服Agent" if state["route"] == "service" else "📈 运营分析Agent"
            st.caption(f"路由结果: {badge}")
            reply = state["messages"][-1]
            text = reply["content"] if isinstance(reply, dict) else reply.content
            st.markdown(text)
            st.session_state.history.append(("assistant", f"{badge} · {text}"))
            if state.get("pending"):
                st.session_state.pending = state["pending"]
                st.rerun()

# ---------------- Tab3: 数据概览 ----------------
with tab3:
    st.subheader("真实 Olist 数据（只读 SQL，经守卫层过滤）")
    from app.agent.analytics import run_readonly_sql

    presets = {
        "各状态订单数": "SELECT order_status, COUNT(*) AS n FROM olist_orders GROUP BY 1 ORDER BY n DESC",
        "GMV Top5 品类": (
            "SELECT t.product_category_name_english AS 品类, ROUND(SUM(i.price),0) AS GMV "
            "FROM olist_order_items i JOIN olist_products p USING(product_id) "
            "JOIN category_translation t USING(product_category_name) "
            "GROUP BY 1 ORDER BY GMV DESC LIMIT 5"
        ),
        "月度订单量趋势": (
            "SELECT substr(order_purchase_timestamp,1,7) AS 月份, COUNT(*) AS 订单数 "
            "FROM olist_orders GROUP BY 1 ORDER BY 1"
        ),
        "支付方式分布": "SELECT payment_type, ROUND(SUM(payment_value),0) AS 金额 FROM olist_order_payments GROUP BY 1 ORDER BY 金额 DESC",
    }
    name = st.selectbox("选择报表", list(presets))
    sql = st.text_area("SQL（可改，守卫层只放行 SELECT）", presets[name], height=90)
    if st.button("执行", key="run_sql"):
        r = run_readonly_sql(sql)
        if not r["ok"]:
            st.error(f"被守卫层拒绝或执行失败: {r['error']}")
        else:
            st.dataframe(r["rows"], use_container_width=True)
            st.caption(f"{r['row_count']} 行 · {r['elapsed_ms']} ms · 自动 LIMIT 50")
