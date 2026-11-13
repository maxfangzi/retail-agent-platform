# 简历表述与面试问答（内部材料，不提交 GitHub）

## 一、简历项目条目（可直接粘贴）

**零售电商智能运营 Agent 平台**（个人项目 · 独立设计与开发）
技术栈：LangGraph · RAG(ChromaDB) · FastAPI · Mistral AI · Langfuse · Docker Compose · pytest

- 基于 10 万条 Olist 真实电商订单数据，设计并实现客服 Agent 平台：RAG 知识库问答、LangGraph 函数调用智能体（6 个订单查询工具）、人工审核工作流三大模块，FastAPI 提供 REST API
- 设计 Human-in-the-loop 敏感操作管控：退款工单通过 LangGraph interrupt() 暂停、人工 API 审批后恢复执行；全部工具只读，遵循最小权限原则
- 构建安全防护层：正则规则引擎拦截提示词注入（返回 400）、手机号/邮箱 PII 脱敏后再进模型
- 建立评测回归体系：18 条六类评测用例（检索命中率断言），当前通过率 100%；将切块器版本纳入向量索引指纹，杜绝索引静默不更新导致的检索回退
- 集成 Langfuse 全链路 tracing（未配置时零开销降级）、Mistral 双模型成本路由（fast/premium）、429 指数退避重试；提供 Docker Compose 一键部署（含自托管观测栈 profile）

（如果简历空间紧张，保留前 3 条即可）

## 二、面试高频问答

**Q: 为什么用 LangGraph 而不是直接写 while 循环调 API？**
A: 三个理由：① 状态图让"工具调用循环"结构化，tools_condition 条件边天然处理"要不要调工具"；② checkpointer 内置会话状态持久化，interrupt/resume 的人工审核流程不用自己写状态机；③ 生产可换 SqliteSaver/PostgresSaver 做断点恢复，架构不用动。

**Q: 怎么防止模型编造订单信息？**
A: 不靠 prompt 求它。架构上把"事实"和"生成"分离：订单状态、金额、物流全部只能通过 6 个只读 SQL 工具查询，system prompt 规定涉及订单必须先查工具；政策类问题走 RAG，检索分数低于阈值直接转人工不给模型发挥机会。

**Q: 退款这种操作为什么安全？**
A: 三层：① 工具本身不是"执行退款"而是"登记待审核工单"；② LangGraph interrupt() 在登记前暂停整张图，前端拿到 pending_review；③ 人工调 /agent/review 批准或驳回后 Command(resume) 恢复，Agent 拿到结果继续。Agent 从头到尾没有数据库写权限。

**Q: 提示词注入怎么防的？**
A: 入口规则引擎（正则匹配"忽略指令/规则/设定"等模式）直接 400，不进模型；同时 PII 脱敏防止客户敏感信息流向外部 API。规则引擎的优点是零成本、可解释、延迟为零；缺点是覆盖不了变形攻击，生产上会再加一层基于分类模型的双重检测，这是文档里写明的已知边界。

**Q: 评测集怎么设计的？**
A: 18 条用例覆盖六类问题（配送/退款/支付/评价/超纲/安全），每条断言必须命中的知识文件和必须包含的关键词。支持 --retrieval-only 离线跑检索层回归。实战价值：改切块策略时它抓住了"boleto 过期"用例从命中变丢失的回退，倒逼我把切块器版本纳入索引指纹——这类"改了 A 坏了 B"没有评测集根本发现不了。

**Q: RAG 切块怎么做的？为什么？**
A: 两级切块：先按 '##' 标题分段，再把段内 '- **问**' 形式的问答对逐条拆开。整段切块时多条 QA 语义互相稀释，多语言 embedding 下相似度被拉低导致检索不命中；问答粒度切块后命中分数从 0.40 提升到 0.60。

**Q: 如果要上生产，下一步做什么？**
A: ① InMemorySaver 换 PostgresSaver 支持多副本；② 评测接 CI 每次 PR 回归；③ 注入检测加分类模型双保险；④ 退款工单接审批系统（飞书/钉钉卡片）；⑤ 多轮对话上下文压缩控制 token 成本。

## 三、GitHub 仓库发布清单（M5 收尾）

1. 确认 .gitignore 覆盖：data/ chroma_db/ .env review_queue/（已覆盖 data/，需核对）
2. 推到新 GitHub 仓库（如 retail-agent-platform），README 即门面
3. 简历项目条目链接仓库；面试前用 run_api.bat 本地起服务，curl 三连演示

## 四、你还需要会讲的基础概念（投递前自测）

- HTTP API 是什么、FastAPI 的 request/response 生命周期
- 什么是 embedding / 向量检索 / cosine 相似度（用自己的话说一遍）
- 函数调用（function calling）的原理：模型输出 JSON → 代码执行 → 结果回传
- LangGraph 的 node/edge/state/checkpointer 各是什么
- 为什么要 human-in-the-loop、为什么工具要最小权限
