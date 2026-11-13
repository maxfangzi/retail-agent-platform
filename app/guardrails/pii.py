# -*- coding: utf-8 -*-
"""入口防护层：PII 脱敏 + 提示注入检测。

企业级要点（面试必讲）：
1. PII 脱敏：用户消息里的手机号/邮箱在进入 LLM 前替换为占位符——
   最小化个人数据出域，符合 GDPR/个保法思路；
2. 注入检测：拦截"忽略之前所有指令"类越狱尝试（规则版），
   生产环境会叠加分类器模型，这里先立骨架。
"""
import re

# 中国大陆手机号 / 邮箱 / 巴西手机号（+55 开头，Olist 场景）
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已脱敏]"),
    (re.compile(r"\+55\s?\(?\d{2}\)?\s?9?\d{4}-?\d{4}"), "[手机号已脱敏]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱已脱敏]"),
]

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"忽略.{0,8}(指令|规则|设定|prompt)", re.I),
    re.compile(r"ignore (all |any )?(previous|prior|above)", re.I),
    re.compile(r"(你|now)现在是?(一个)?(无限制|没有限制|DAN)", re.I),
    re.compile(r"(泄露|输出|打印|print).{0,12}(系统提示|system prompt)", re.I),
]


def mask_pii(text: str) -> str:
    """把消息中的手机号/邮箱替换成占位符。"""
    for pattern, repl in _PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def detect_injection(text: str) -> tuple[bool, str]:
    """返回 (是否疑似注入, 命中说明)。"""
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return True, f"命中规则: {m.group(0)}"
    return False, ""
