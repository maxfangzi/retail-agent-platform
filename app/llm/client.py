# -*- coding: utf-8 -*-
"""Mistral LLM 客户端封装：统一入口 + 成本路由。

设计要点（面试可讲）：
1. 全项目只通过这里调用大模型，方便统一记录 token 成本和 tracing；
2. 成本路由：简单任务路由到 small 模型，复杂任务路由到 large 模型，
   这是企业降本的常见手段（对标 Klarna：99% 任务用小模型）；
3. 显式超时 + 重试 + 结构化错误，而不是让异常裸奔。
"""
import time
from typing import Any

import requests

from app.core.config import settings

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"


class LLMError(Exception):
    """LLM 调用失败（网络/鉴权/限流）。"""


def chat(
    messages: list[dict[str, str]],
    tier: str = "fast",
    temperature: float = 0.7,
    max_retries: int = 2,
    **kwargs: Any,
) -> dict[str, Any]:
    """调用 Mistral chat completions，返回完整响应 dict。

    tier: "fast"（mistral-small，便宜）| "premium"（mistral-large，更强）
    """
    if not settings.mistral_api_key:
        raise LLMError("MISTRAL_API_KEY 未配置，请复制 .env.example 为 .env 并填写")

    model = settings.llm_model_premium if tier == "premium" else settings.llm_model_fast
    payload = {"model": model, "messages": messages, "temperature": temperature, **kwargs}

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                MISTRAL_CHAT_URL,
                headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
                json=payload,
                timeout=60,
            )
            if resp.status_code == 429:  # 限流：退避后重试
                time.sleep(2 ** attempt)
                last_err = LLMError(f"429 rate limited: {resp.text[:200]}")
                continue
            if resp.status_code != 200:
                raise LLMError(f"Mistral {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            time.sleep(2 ** attempt)

    raise LLMError(f"Mistral 调用失败（已重试 {max_retries} 次）: {last_err}")


def chat_text(messages: list[dict[str, str]], tier: str = "fast", **kwargs: Any) -> str:
    """只取回复文本的便捷方法。"""
    data = chat(messages, tier=tier, **kwargs)
    return data["choices"][0]["message"]["content"]


def cost_of(data: dict[str, Any]) -> float:
    """按 Mistral 牌价估算单次调用成本（USD）。价格可能调整，以官网为准。"""
    price_in = {"mistral-large-latest": 2.0, "mistral-small-latest": 0.1}
    price_out = {"mistral-large-latest": 6.0, "mistral-small-latest": 0.3}
    model = data.get("model", "mistral-small-latest")
    usage = data.get("usage", {})
    pin = price_in.get(model, 0.1)
    pout = price_out.get(model, 0.3)
    return usage.get("prompt_tokens", 0) / 1e6 * pin + usage.get("completion_tokens", 0) / 1e6 * pout
