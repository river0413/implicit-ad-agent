# 架构决策记录（ADR）· 隐性广告识别项目

> 对应计划表任务 0.2 / 里程碑 M0。每条决策白纸黑字，避免后期反复。
> 状态标记：**已定** = 生效执行；**观察** = 生效但设有复审触发条件。
> 修改流程：任何人想推翻某条决策，须在周会上提出，说明"新事实是什么"，4 人过半同意后**修改本文档并注明日期**，不允许口头改。

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v1.0 | 2026-07-12 | 初稿，覆盖 LLM / 编排 / 向量库 / 前端 / 降级阶梯等 10 项决策 |

**签字确认**（M0 验收要求 4 人签字）：

- [ ] L 姚家辉　- [ ] N 江灵均　- [ ] V 叶泽楷　- [ ] D 王一帆

---

## ADR-001 · LLM 选型：厂商无关抽象 + 分档用模

**状态**：已定（模型具体型号为"观察"）

**背景**：系统所有智能体都以 LLM 为大脑。硬指标：① 工具调用（tool-use / JSON 输出）可靠；② 中文理解强（暗广话术是中文语境）；③ 成本可承受（学生项目，无大额预算）；④ 国内可直连（演示现场不能翻车）。

**决策**：
1. **代码层永远厂商无关**：统一走 OpenAI 兼容端点（`langchain-openai`，`impad/llm.py` 已实现），换模型只改 `.env` 的 `OPENAI_BASE_URL` + `LLM_MODEL`，代码零改动。
2. **分档用模**，而不是全程一个模型：

| 档位 | 用途 | 默认选型 | 说明 |
| --- | --- | --- | --- |
| 主力文本 | NLP 智能体、意图/话术分析、报告生成 | **DeepSeek-chat（V3 系）** | 中文强、价格约为 GPT-4o 的 1/10 量级、国内直连 |
| 路由/轻任务 | Supervisor 路由、摘要、字段抽取 | 同上或更便宜的小模型（如 qwen-turbo / glm-4-flash） | 路由决策简单，别烧强模型 |
| 多模态视觉 | 图文一致性、Logo/商品识别、OCR 兜底 | **Qwen-VL 系（qwen-vl-plus / qwen2.5-vl）**，走 DashScope 的 OpenAI 兼容端点 | P2 起步期用 VLM 替代自训 CLIP/YOLO，接口不变可后换 |
| 强推理（少量） | Judge 反思质询、低置信复核 | deepseek-reasoner 或届时最强可用模型 | 只在低置信分支触发，控制调用量 |

3. **成本纪律**：设每人每阶段 API 预算上限（建议 P2 前 ≤50 元/人，P3–P5 ≤150 元/人）；对固定样本的调用结果**做缓存**；批量评估跑 test 集前先在 10 条小样本上确认 prompt 稳定。

**否决的备选**：
- 纯 OpenAI GPT 系：国内访问不稳 + 成本高，只作对照实验备选。
- 本地部署开源 Qwen/GLM：前期无 GPU、运维负担重。留作 L2/L3（"可私有化部署"是答辩加分叙事，不是前期路径）。

**复审触发**：任何一档模型在 LangSmith 评测集上工具调用失败率 >5%，或单阶段成本超预算 50%，即在周会重选该档。

---

## ADR-002 · 编排框架：LangGraph + LangChain

**状态**：已定

**背景**：需要图式编排（条件路由、共享状态、检查点持久化）来实现 Supervisor→专家→Judge 架构，且要能在 LangSmith 看到每步轨迹。

**决策**：**LangGraph**（StateGraph/Node/Edge/Checkpointer）为主干，LangChain 提供模型与工具统一接口。Python **3.10**（见 ADR-009）。`requirements.txt` 锁定版本，升级须过一遍 `pytest` 冒烟。

**否决的备选**：
- **CrewAI**：抽象层太高，路由和状态细节难控，不利于论文里讲清架构。
- **AutoGen**：对话驱动范式，与"证据累积 + 加权聚合"的状态机模型不匹配。
- **自研编排**：4 人 6 个月造不起轮子，且失去 LangSmith 生态。

**已验证**：多智能体骨架（Supervisor+3 专家+Judge）已在 `impad/graph.py` 零 Key 跑通（2026-07-12）。

---

## ADR-003 · 向量库与 Embedding：Chroma 起步，bge 系中文向量

**状态**：观察

**背景**：两处用向量检索——① RAG 法规/判例库（P3）；② 博主历史发文的情景记忆（P4）。数据规模：法规条款 <1 万块，博主历史 <10 万条，单机演示场景。

**决策**：
1. **向量库用 Chroma**：嵌入式、零运维、本地持久化、LangChain 原生集成。法规库与情景记忆用**两个独立 collection**，别混在一起。
2. **Embedding 默认本地 `BAAI/bge-small-zh-v1.5`**（sentence-transformers 加载，零成本、中文效果好、CPU 可跑）；若后续检索质量不够，升级 `bge-m3` 或切云端 embedding 接口（DashScope text-embedding-v3）。
3. Embedding 模型一旦入库就**锁定**——中途换模型必须整库重建，切换前先算清重建成本。

**否决的备选**：Milvus（需独立部署，前期纯负担）、Pinecone（境外 SaaS，合规与网络风险）、FAISS 裸用（无持久化与元数据过滤，还得自己包一层）。

**复审触发**：向量总量 >100 万，或需要多用户并发在线服务时，迁移 Milvus（Chroma 的 API 风格与之接近，迁移成本可控）。

---

## ADR-004 · 前端：Streamlit（前后端分离，前端可弃）

**状态**：已定

**背景**：前端只为演示服务——输入帖子/链接 → 展示判定 + 证据链高亮 + 法规引用。评委看的是证据链，不是 UI 炫技。

**决策**：**Streamlit** 做演示前端；所有业务逻辑留在 FastAPI 后端，前端只调 `/analyze` 接口。这样前端随时可换（Gradio/React）而不动系统本体。

**否决的备选**：
- **Gradio**：单输入单输出的 demo 更快，但多区块布局（证据链分栏、逐条法规展开）表达力弱于 Streamlit。若 P5 时间极紧，允许降级为 Gradio。
- **React/Vue 自建**：4 人无前端主责，投入产出比不划算。竞赛需要更好看的界面时再议（L3）。

---

## ADR-005 · 后端与部署：FastAPI + 腾讯云 CVM，Docker 留到 P5

**状态**：已定

**决策**：
1. **FastAPI + uvicorn** 暴露 `POST /analyze`、`GET /health`（已实现），Swagger 文档自带（`/docs`）。
2. 开发期一律**本地 venv**，不上 Docker；**P5 集成阶段**再写 Dockerfile 并部署到**腾讯云普通服务器（CVM）**。
3. 否决 AWS Lambda 等 Serverless：LLM 链路耗时长易超时、无状态与 Checkpointer 冲突、国内访问摩擦大。
4. **演示兜底**：`samples/` 预置固定样本 + 结果缓存，现场演示不依赖实时爬取与实时 LLM 调用成功。

---

## ADR-006 · 观测与评估：LangSmith（注意数据脱敏）

**状态**：已定

**决策**：
1. 全程开 **LangSmith** 追踪（Thought/Action/Observation 轨迹），调试先看轨迹再猜。
2. 评估双轨：LangSmith Dataset+Evaluation 管回归（prompt 改了跑一遍，防退化）；本地 `scikit-learn` 脚本出论文指标（P/R/F1/AUC-ROC/消融）。
3. **红线**：LangSmith 是境外托管服务，轨迹会上传帖子内容。标注数据入库前做脱敏（去用户名/头像/可识别 ID）；含真实个人信息的样本用 `LANGSMITH_TRACING=false` 跑。

---

## ADR-007 · 工具协议：原生 LangChain tools 起步，FastMCP 是 L2

**状态**：已定

**决策**：P2 工具舱全部用 LangChain `@tool` + Pydantic schema 实现，每个工具三要素：**明确出入参、返回"证据"字段、graceful fallback（无图/超时不崩）**。FastMCP 封装（把工具舱变成 MCP Server）列为 **L2 拓展**：只有当 ≥6 个工具全绿且 P4 按期，才动手；届时只是给现有工具加一层壳，接口不变。A2A 协议为 L3，默认不做。

**理由**：MCP 是研究报告卖点但不是功能必需；先用原生 tools 保进度，"接口不变、随时可包壳"让这个决策可逆。

---

## ADR-008 · 降级阶梯与降级决策点

**状态**：已定（本条是全项目的"永不翻车"保险，优先级最高）

**阶梯定义**（同计划表第 6 节）：

| 层级 | 内容 |
| --- | --- |
| **L0 保底** | 单体 ReAct 智能体 + 文本&图像（多模态 LLM）+ RAG 法规 + 结构化报告 + 三元评估 + Web demo |
| **L1 应做** | Supervisor + 3 专家 + Judge；情景记忆 + 偏好偏移；加权聚合 |
| **L2 可做** | 反思/辩论；评论区水军；图像取证；HITL 界面；FastMCP |
| **L3 冲刺** | A2A；程序记忆/自我优化；ASTRA 红队；跨平台矩阵 |

**降级决策点**（关口日期一到，当场决策，不拖"再等一周"）：

| 检查点 | 日期 | 未达标时的动作 |
| --- | --- | --- |
| M1 | 08-17 | κ<0.6 或数据 <1500 → P2 压缩到 2 周（砍 2.5/2.7 两个工具），把时间还给数据 |
| M3 | 10-05 | MVP 未端到端跑通 → **冻结 L1 范围**：P4 只做 Supervisor 路由 + 情景记忆，砍辩论与评论 agent |
| M4 | 11-16 | 暗广召回未超 XGBoost 基线 → 不再加智能体，P5 全力调优已有链路 + 打磨评估与论文（论文叙事转"架构 + 可解释性优势"） |
| M5 | 12-14 | 评估不完整 → 论文降级为"系统论文 + 初步实验"，保结题与软著 |

**升级准则**：只有当前层级**全部完成且里程碑提前**，才允许动下一层级的任务；任何人不得跳层"顺手做个 L3"。

---

## ADR-009 · 运行环境：Python 3.10、venv、依赖锁定

**状态**：已定

**决策**：Python **3.10**（本机实际 3.10.11，`.python-version` 已定），`python -m venv .venv` 建环境（本机无 uv，别指望）。依赖统一进 `requirements.txt`（pytest 是必装不是可选）。所有会打印中文的脚本开头必须加 `sys.stdout.reconfigure(encoding="utf-8")`（Windows GBK 坑，已在 `run_demo.py` 示范）。文档中原写的 3.11 以本条为准。

---

## ADR-010 · 结构化输出策略：json_mode + 英文字段 + Pydantic 校验

**状态**：已定

**背景**：DeepSeek 等国产端点对 LangChain 默认 function-calling 式 `with_structured_output` 支持不稳（已实测踩坑）。

**决策**：所有需要结构化输出的 LLM 调用统一采用：`with_structured_output(..., method="json_mode")` + **prompt 中显式约束英文字段名**（verdict/confidence/evidence 等）+ Pydantic 二次校验。校验失败重试 1 次，仍失败则走**规则降级**（如 `nlp_agent` 的关键词规则），保证图永不因格式错误中断。**不要改回默认结构化模式。**

---

## 附：决策速查表

| 决策项 | 结论 | ADR |
| --- | --- | --- |
| LLM | 厂商无关端点；DeepSeek-chat 主力 / Qwen-VL 视觉 / 便宜模型做路由 | 001 |
| 编排 | LangGraph + LangChain | 002 |
| 向量库 | Chroma（>100万向量再迁 Milvus） | 003 |
| Embedding | bge-small-zh-v1.5 本地起步 | 003 |
| 前端 | Streamlit（时间紧可降 Gradio） | 004 |
| 后端/部署 | FastAPI；腾讯云 CVM；Docker 留 P5 | 005 |
| 观测 | LangSmith（数据脱敏红线） | 006 |
| 工具协议 | 原生 @tool；FastMCP=L2；A2A=L3 | 007 |
| 降级阶梯 | L0–L3 + 四个降级决策点（M1/M3/M4/M5） | 008 |
| 环境 | Python 3.10 + venv + UTF-8 强制 | 009 |
| 结构化输出 | json_mode + 英文字段 + Pydantic + 规则降级 | 010 |
