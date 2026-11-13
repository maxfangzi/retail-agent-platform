# -*- coding: utf-8 -*-
"""Langfuse tracing 集成（可选：.env 里配置了 key 才启用）。

设计：tracing 是横切关注点，独立成模块；没配 key 时全部调用退化为 no-op，
业务代码零感知。记录: 每次 RAG 问答/Agent 调用的输入、输出、检索命中、token 成本。
"""
import functools
import json
import time
from typing import Any

from app.core.config import settings

_enabled = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
_client = None
if _enabled:
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:
        _enabled = False


def is_enabled() -> bool:
    return _enabled


def trace_rag_answer(question: str, result_fn) -> dict:
    """包一层 RAG 问答，记录 trace：问题/回答/来源/耗时/成本。"""
    start = time.time()
    result: dict = result_fn()
    if _enabled and _client:
        try:
            _client.trace(
                name="rag_answer",
                input={"question": question},
                output={"answer": result.get("answer", "")[:500]},
                metadata={
                    "sources": json.dumps(result.get("sources", []), ensure_ascii=False),
                    "latency_s": round(time.time() - start, 2),
                    "cost_usd": result.get("cost_usd"),
                    "usage": result.get("usage"),
                },
            )
            _client.flush()
        except Exception:
            pass  # tracing 故障绝不能影响主业务
    return result


def traced(name: str):
    """通用装饰器：函数返回 dict 时自动上报一条 trace。"""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            start = time.time()
            out = fn(*args, **kwargs)
            if _enabled and _client and isinstance(out, dict):
                try:
                    _client.trace(
                        name=name,
                        input={"args": [str(a)[:200] for a in args], "kwargs": {k: str(v)[:200] for k, v in kwargs.items()}},
                        output={k: str(v)[:300] for k, v in out.items()},
                        metadata={"latency_s": round(time.time() - start, 2)},
                    )
                    _client.flush()
                except Exception:
                    pass
            return out

        return wrapper

    return deco
