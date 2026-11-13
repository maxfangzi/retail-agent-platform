# -*- coding: utf-8 -*-
"""SQL 只读守卫单测（不依赖网络/LLM）。"""
import pytest

from app.agent.analytics import sanitize_sql, run_readonly_sql


class TestSanitizeSql:
    @pytest.mark.parametrize("evil", [
        "DROP TABLE olist_orders",
        "DELETE FROM olist_orders WHERE 1=1",
        "INSERT INTO olist_orders VALUES (1)",
        "UPDATE olist_orders SET order_status='x'",
        "SELECT 1; DELETE FROM olist_orders",          # 多语句
        "select * from t -- comment\n; drop table t",  # 注释藏写操作
        "PRAGMA table_info(olist_orders)",
        "ATTACH DATABASE 'x.db' AS x",
        "",
        "   ",
    ])
    def test_blocks_writes(self, evil):
        with pytest.raises(ValueError):
            sanitize_sql(evil)

    def test_select_passes_and_gets_limit(self):
        assert sanitize_sql("select count(*) from olist_orders") == \
            "select count(*) from olist_orders LIMIT 50"

    def test_existing_limit_kept(self):
        assert sanitize_sql("select * from olist_orders LIMIT 3").endswith("LIMIT 3")


class TestRunReadonlySql:
    def test_happy_path(self):
        r = run_readonly_sql("SELECT order_status, COUNT(*) c FROM olist_orders GROUP BY 1 ORDER BY c DESC")
        assert r["ok"] is True
        assert r["row_count"] >= 1
        assert {"order_status", "c"} <= set(r["columns"])

    def test_bad_sql_returns_error_not_raises(self):
        r = run_readonly_sql("SELECT no_such_col FROM olist_orders")
        assert r["ok"] is False
        assert "error" in r

    def test_write_returns_blocked(self):
        r = run_readonly_sql("DROP TABLE olist_orders")
        assert r["ok"] is False
        assert "禁止" in r["error"] or "SELECT" in r["error"]
