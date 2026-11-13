# -*- coding: utf-8 -*-
"""RAG 客服服务：检索增强的客服回答（含引用出处）。

流程: 用户问题 → 向量检索知识块 → 拼装带出处的 Prompt → Mistral 生成 →
      回复 + 引用列表。检索分数过低时明确说"不知道"，不编造——
      这是与玩具 demo 的核心区别。
"""
from app.core.tracing import trace_rag_answer
from app.llm import client as llm
from app.rag import store

SYSTEM_PROMPT = """你是电商平台"智购"的官方客服。回答规则：
1. 只依据【参考资料】回答；资料里没有的信息，回答"这个问题我需要转人工为您确认"，绝不编造。
2. 涉及具体订单（订单号/物流/退款进度）时，说明"我需要先为您查询订单"，不要凭空猜测状态。
3. 语气礼貌专业，回答控制在 150 字以内。
4. 若使用了某条资料，在句末用 [来源: 文件名] 标注。"""

NO_ANSWER = "这个问题超出了我的知识范围，已为您转接人工客服，请稍候。"
MIN_SCORE = 0.35  # 检索相似度低于此值视为知识库无答案


def _do_answer(question: str, hits: list[dict]) -> dict:
    context = "\n\n".join(
        f"[资料{i+1}] ({h['file']} / {h['section']})\n{h['text']}"
        for i, h in enumerate(hits)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"【参考资料】\n{context}\n\n【客户问题】\n{question}"},
    ]
    data = llm.chat(messages, tier="fast", temperature=0.2)
    return {
        "answer": data["choices"][0]["message"]["content"],
        "sources": [{"file": h["file"], "section": h["section"], "score": h["score"]} for h in hits],
        "retrieved": hits,
        "usage": data.get("usage"),
        "cost_usd": round(llm.cost_of(data), 6),
    }


def answer(question: str) -> dict:
    """回答一个客服问题。返回 {'answer', 'sources', 'retrieved'}。"""
    hits = store.retrieve(question, top_k=4)
    if not hits or hits[0]["score"] < MIN_SCORE:
        no_hit = {"answer": NO_ANSWER, "sources": [], "retrieved": hits}
        return trace_rag_answer(question, lambda: no_hit)
    return trace_rag_answer(question, lambda: _do_answer(question, hits))
