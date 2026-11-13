# Retail Agent Platform · 零售电商智能运营 Agent 平台

一个面向真实业务场景的**企业级客服 Agent 平台**：基于巴西 Olist 公开的 10 万级真实电商订单数据，
实现「知识库问答（RAG）+ 订单工具调用（LangGraph Agent）+ 人工审核（Human-in-the-loop）+ 安全防护 + 评测回归 + 可观测性」的完整链路。

> 技术栈：Python 3.12+ · FastAPI · LangGraph · ChromaDB · sentence-transformers · Mistral AI · Langfuse · Docker Compose · pytest

## 为什么做这个项目

真实生产环境的 LLM Agent 不是"调一下 API"就完事，难点全在工程化：
模型会编造订单状态怎么办？客户想套出系统提示词怎么办？Agent 要执行退款这种敏感操作怎么办？
答案质量怎么回归测试？本项目针对这五个问题各给出了一套可验证的方案。

## 架构

```
                 ┌──────────────────── API 层 (FastAPI) ────────────────────┐
                 │  /rag/ask          /agent/chat          /agent/review    │
                 └──────┬─────────────────────┬─────────────────────┬───────┘
                        │                     │                     │
                 ┌──────▼──────┐      ┌───────▼────────┐    ┌───────▼────────┐
                 │ 防护层       │      │ LangGraph Agent │    │ 人工审批恢复    │
                 │ 注入拦截     │      │ Mistral 函数调用 │    │ interrupt()/   │
                 │ PII 脱敏     │      │ 6 个订单工具     │    │ Command(resume)│
                 └──────┬──────┘      └───────┬────────┘    └────────────────┘
                        │                     │
                 ┌──────▼──────┐      ┌───────▼────────┐          ┌──────────────┐
                 │ RAG 检索     │      │ SQLite (Olist)  │          │ Langfuse     │
                 │ ChromaDB     │      │ 9.9万订单只读SQL │          │ tracing(可选) │
                 │ 多语言向量    │      │ 最小权限原则     │          └──────────────┘
                 └─────────────┘      └────────────────┘
```

## 核心企业级设计（对应面试高频问题）

| 问题 | 方案 | 代码 |
|---|---|---|
| 模型编造订单信息 | 工具强制查库：Agent 只能通过 6 个只读 SQL 工具获取订单事实，system prompt 红线约束 | `app/agent/graph.py` |
| 敏感操作失控 | 退款走 `interrupt()` 暂停 + 人工 `/agent/review` 批准后才落盘；Agent 无直写数据库权限 | `app/agent/graph.py:68` |
| 提示词注入 / PII 泄露 | 入口规则引擎：注入模式正则拦截 400，手机号/邮箱脱敏后再进模型 | `app/guardrails/pii.py` |
| 幻觉答案无法回归 | 18 条评测用例六类覆盖，检索质量一键回归（当前 18/18），切块器版本纳入索引指纹防止静默回退 | `app/evals/` `scripts/run_evals.py` |
| 线上黑盒 | Langfuse tracing 记录每次问答的输入/来源/延迟/token 成本，未配置时零开销降级 | `app/core/tracing.py` |
| 成本控制 | 双模型路由：FAQ 生成用 small 档，复杂推理可切 large 档 | `app/llm/client.py` |

## 快速开始

```bash
# 1. 环境
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # Windows
# 2. 配置：复制 .env.example 为 .env，填入 MISTRAL_API_KEY
# 3. 数据（下载 Olist CSV 并入库 SQLite）
python scripts\download_data.py
python scripts\seed_db.py
# 4. 构建知识库索引 + 跑评测
python scripts\run_evals.py --retrieval-only        # 预期 18/18
# 5. 启动服务
uvicorn app.api.main:app --reload
```

### 演示

```bash
# RAG 知识问答（带出处引用）
curl -X POST http://127.0.0.1:8000/rag/ask -H "Content-Type: application/json" \
  -d '{"question": "超过预计送达时间还没收到货怎么办？"}'

# Agent 工具调用 + 退款人工审核（返回 pending_review）
curl -X POST http://127.0.0.1:8000/agent/chat -H "Content-Type: application/json" \
  -d '{"message": "订单 99a478866da877444aa38b616f029de8 超期未送达，我要退款", "thread_id": "c-1001"}'

# 人工批准后 Agent 继续执行
curl -X POST http://127.0.0.1:8000/agent/review -H "Content-Type: application/json" \
  -d '{"thread_id": "c-1001", "approved": true, "note": "已核实超期"}'
```

### Docker 部署（可选，本机未装 Docker 时用上一节方式）

```bash
docker compose up -d                          # 只起 API
docker compose --profile tracing up -d        # API + 自托管 Langfuse (localhost:3000)
```

## 项目结构

```
app/
  api/main.py          # FastAPI：防护层入口 + RAG + Agent + 人工审批
  agent/graph.py       # LangGraph 状态图：函数调用循环 + interrupt 人工审核
  rag/store.py         # 向量库：两级切块、幂等索引、指纹防回退
  rag/service.py       # RAG 问答编排：检索→拼上下文→生成→出处
  tools/odata.py       # 订单数据工具层：只读 SQL + 错误封装
  guardrails/pii.py    # 注入检测 + PII 脱敏
  llm/client.py        # Mistral 封装：双模型路由 + 429 退避重试 + 成本核算
  core/tracing.py      # Langfuse 可观测性（可选降级）
  evals/eval_set.jsonl # 18 条评测用例
knowledge/             # 客服知识库（配送/退款/支付/会员 4 篇政策文档）
scripts/               # 数据下载/入库/评测/冒烟
tests/                 # pytest 单元测试
```

## 数据来源

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)（100k 匿名化真实订单），仅用于学习演示；本项目入库订单、支付、评价、商品四张表共 10 万+ 行。

## License

MIT
