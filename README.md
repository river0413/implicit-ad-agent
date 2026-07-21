# 隐性广告识别 · LangGraph 多智能体系统

> 面向社交媒体合规审查的**可解释多模态隐性广告检测系统**，输入帖子（文本 + 图片 + 博主历史 + 评论区），自动判定 **明广 / 暗广 / 非广**，输出带证据链与法规依据的审查报告。

---

## 项目概览

### 一句话定义

构建一个 **LangGraph 驱动的多智能体系统**，融合多模态行为特征与文本推断，对社交媒体内容进行可解释的隐性广告识别。

### 候选项目名

| 中文 | 英文 |
|------|------|
| 基于多智能体多模态推理的隐性广告可解释识别 | Explainable Implicit Advertisement Detection Based on Multi-Agent Multimodal Reasoning |
| 面向社会媒体合规审查的 LangGraph 驱动隐性广告检测系统 | LangGraph-Driven Implicit Advertisement Detection System for Social Media Compliance Review |
| 面向可解释隐性广告识别的记忆增强多模态智能体系统 | Memory-Augmented Multimodal Agent System for Explainable Implicit Advertising Identification |

### 核心策略

将传统流水线（BERT+CNN+XGBoost）中的各模型**封装为智能体的工具**，在上层构建会思考、会解释的"指挥系统"——Supervisor → 专家 Agent → Judge → 审查报告。

### 团队角色

| 代号 | 角色 | 主责 |
|------|------|------|
| **L** | 负责人 & 架构编排 | LangGraph 主干、状态设计、集成、进度 |
| **N** | NLP / LLM 工程 | 文本智能体、Prompt 工程、RAG |
| **V** | 视觉 / 多模态工程 | 视觉智能体、OCR/CLIP、图文一致性 |
| **D** | 数据 / 评估 | 爬虫、标注、行为分析、指标、论文 |

---

## 目标架构

```
输入：帖子（文本 + 图片 + 博主主页 + 评论区）
                │
   ┌────────────▼──────────────┐
   │   Supervisor 主控智能体    │  ← LangGraph 编排
   └──┬──────┬───────┬──────┬──┘
      ▼      ▼       ▼      ▼
   NLP    视觉    行为    RAG检索
  智能体  智能体  智能体  法规/判例
      └──────┴───────┴──────┘
                │
                ▼
   ┌─────────────────────────┐
   │  Judge / 聚合智能体       │
   │  加权聚合 + 反思质询      │
   └───────────┬─────────────┘
               ▼
   结构化审查报告：判定 + 证据链 + 法规引用
```

**当前骨架（已实现）**：

```
START → Supervisor（按输入排专家队列：纯文本跳过视觉、无历史跳过行为）
          → NLP 专家（LLM；未配 Key 自动降级为规则，零成本可跑）
          → 视觉专家（YOLO11 物体检测 + OCR 抠图内文字回灌关键词 + 加权焦点；未装依赖自动降级）
          → 行为专家（占位规则，P3 接 EMA+Chroma 记忆）
        → Judge（按专家可靠度加权聚合 + 低置信反思质询） → END
```

---

## 分阶段计划

| 阶段 | 名称 | 时段 | 时长 | 关口 |
|------|------|------|------|------|
| P0 | 启动与技能对齐 | 07-09 ~ 07-20 | 2 周 | M0 |
| **P1** | **数据地基与标注规范** | **07-21 ~ 08-17** | **4 周** | **M1** |
| P2 | 工具舱 | 08-18 ~ 09-07 | 3 周 | M2 |
| P3 | 单体智能体 MVP | 09-08 ~ 10-05 | 4 周 | M3 |
| P4 | 多智能体协作 + 记忆 | 10-06 ~ 11-16 | 6 周 | M4 |
| P5 | 系统集成 · 前后端 · 评估 | 11-17 ~ 12-14 | 4 周 | M5 |
| — | 期末缓冲 | 12-15 ~ 01-11 | 4 周 | — |
| P6 | 论文 · 竞赛 · 结题 | 01-12 ~ 02-08 | 4 周 | M6 |

### 降级决策点

| 检查点 | 日期 | 未达标动作 |
|--------|------|-----------|
| M1 | 08-17 | κ<0.6 或数据 <1500 → P2 压缩到 2 周 |
| M3 | 10-05 | MVP 未端到端 → 冻结 L1 范围 |
| M4 | 11-16 | 暗广召回未超 XGBoost 基线 → 全力调优已有链路 |
| M5 | 12-14 | 评估不完整 → 论文降级"系统论文 + 初步实验" |

**产能节奏**：暑假全职（~30h/周）→ 秋季半负荷（~12h/周）→ 期末最小（~3h/周）→ 寒假全职。

---

## 架构决策速查（ADR 摘要）

| # | 决策项 | 结论 |
|---|--------|------|
| 001 | LLM 选型 | 厂商无关端点（OpenAI 兼容）；DeepSeek-chat 主力 / Qwen-VL 视觉 |
| 002 | 编排框架 | LangGraph + LangChain |
| 003 | 向量库 | Chroma 起步（>100 万向量迁 Milvus）；Embedding: `bge-small-zh-v1.5` |
| 004 | 前端 | Streamlit（前后端分离，可弃换 Gradio） |
| 005 | 后端/部署 | FastAPI + uvicorn；腾讯云 CVM；Docker 留 P5 |
| 006 | 观测 | LangSmith 追踪（数据脱敏红线） |
| 007 | 工具协议 | 原生 @tool；FastMCP=L2 拓展；A2A=L3 |
| 008 | 降级阶梯 | L0 保底 → L1 应做 → L2 可做 → L3 冲刺 |
| 009 | 环境 | Python 3.10 + venv + UTF-8 强制 |
| 010 | 结构化输出 | `json_mode` + 英文字段 + Pydantic 校验 + 规则降级 |

---

## 快速开始

```bash
# 1) 建虚拟环境（本机 Python 3.10，推荐 3.11+）
python -m venv .venv

# 2) 激活虚拟环境
source .venv/Scripts/activate        # Windows Git Bash / macOS / Linux
.venv\Scripts\Activate.ps1           # Windows PowerShell

# 3) 装依赖
python -m pip install -r requirements.txt

# 4) 零成本跑通（不需要任何 Key）
python run_demo.py

# 5) 配好 .env 后，用真正的 LLM 跑（会在 LangSmith 出轨迹）
cp .env.example .env                 # 然后填入 Key
python run_demo.py --llm

# 6) 起后端服务
python -m uvicorn app:app --reload   # 打开 http://127.0.0.1:8000/docs
```

### Windows PowerShell 激活

```powershell
.venv\Scripts\Activate.ps1
```

- 若报「无法加载 …… 未数字签名」，临时放行：
  ```powershell
  Set-ExecutionPolicy -Scope Process RemoteSigned
  ```
- 验证 Python：`where.exe python`，第一行应指向 `.venv\Scripts\python.exe`。
- 不想激活也可直接点名：`.venv\Scripts\python.exe run_demo.py`

> `No module named 'langgraph'` = 没激活 venv，依赖装在 venv 里。

---

## 看 LangSmith 轨迹

1. 去 https://smith.langchain.com 注册，拿 API Key。
2. 把 Key 填进 `.env`，确认 `LANGSMITH_TRACING=true`。
3. 运行 `python run_demo.py --llm`。
4. 打开 LangSmith → 项目 `implicit-ad-agent` → 点开最新一条 run。

---

## 目录说明

| 路径 | 作用 |
| --- | --- |
| `impad/hello_graph.py` | 零 Key 的最小图（规则占位），验证环境与轨迹 |
| `impad/graph.py` | 多智能体图的装配（只搭骨架，不写业务逻辑） |
| `impad/agents/supervisor.py` | 主控调度：按输入决定派哪些专家 + 条件路由 |
| `impad/agents/nlp_agent.py` | NLP 专家：LLM 判意图/话术，无 Key 自动降级规则 |
| `impad/agents/vision_agent.py` | 视觉专家：物体检测 + OCR 抠图内文字回灌关键词 + 焦点；缺依赖自动降级 |
| `impad/agents/behavior_agent.py` | 行为专家（占位规则，P3 接 EMA+Chroma） |
| `impad/agents/judge.py` | 加权聚合投票 + 低置信反思质询 |
| `impad/tools/keywords.py` | 广告信号关键词清单 + 6 维可解释特征 |
| `impad/tools/vision.py` | YOLO11 + EasyOCR + 焦点（重依赖惰性导入） |
| `impad/state.py` | 图的共享状态定义 |
| `impad/llm.py` | 厂商无关 LLM 客户端（OpenAI 兼容端点） |
| `impad/config.py` | 读取 `.env` 的集中配置 |
| `app.py` | FastAPI，`POST /analyze`（返回含各专家投票） |
| `run_demo.py` | 一键跑样本；`--image path` 带图分析 |
| `samples/` | 固定测试帖子 + `images/` 测试图 |
| `requirements-vision.txt` | 视觉专家的可选重依赖（不装则视觉自动降级） |
| `tests/` | 冒烟测试 + 多智能体路由/聚合/关键词特征/视觉降级测试（全部零 Key） |
| `docs/` | 项目文档（标注规范、合规登记、数据集卡片、Schema 等） |
| `资料/` | 技术总览、P1 执行指南、Docs 目录总结 |
| `scripts/data/` | 数据采集/清洗/校验/划分脚本 |

---

## 6 维可解释特征（keyword_weights）

每次分析都会附带一份**确定性**的 6 维关键词权重向量（0~1），无需 LLM、零成本可算：

| 维度（英文字段） | 含义 |
| --- | --- |
| `promotion_words` | 促销种草话术 |
| `price_mentions` | 价格 / 优惠提及 |
| `urgency_expressions` | 紧迫 / 稀缺感 |
| `brand_mentions` | 品牌 / 商务合作 |
| `action_words` | 行动召唤（引流下单/扫码/链接） |
| `natural_expression` | 自然表达 / 生活分享（暗广的"外壳"，反向信号） |

用途：① Judge 聚合时多一路证据；② NLP 规则降级里当兜底判据（`ad_pressure`）；③ 前端可画雷达图、论文可解释性分析。

---

## 视觉专家（可选，需装重依赖）

视觉专家对帖子配图做三件事：**物体检测**（YOLO11，80 类）、**OCR 文字识别**（EasyOCR 中英文）、**加权焦点**。

最关键是 OCR：暗广常把广告词印在图上（"扫码领券""第二件半价"），文本专家看不到——视觉专家把图里的文字抠出来**回灌关键词规则**，命中即形成视觉侧证据与投票。

```bash
# 1) 装可选重依赖（约 2~3GB）
python -m pip install -r requirements-vision.txt

# 2) 带图跑多智能体图
python run_demo.py --image samples/images/test_image.jpg

# 3) API：POST /analyze 加可选字段
#    {"text": "分享个好物～", "image_path": "samples/images/test_image.jpg"}
```

**不装也没关系**：`vision_agent` 探测到依赖缺失会自动投空票（`confidence=0`，Judge 忽略）。

---

## 数据 Schema v2.0

标注层与内容层分离，通过 `post_id` 关联，保留两人独立原始判断。

### 内容记录结构（精简版）

```
post_id            → 标识（SHA-256 hash 前 24 位）
platform           → 平台标识（wechat_official_account / weibo_public_account / web_public）
blogger_id         → 博主标识（脱敏 hash）
published_at       → 发布时间（ISO 8601 +08:00，提取不到填 null）
title              → 标题（可为 null）
text               → 正文（含 <图片N> 标记）
media[]            → 媒体（ref, source_url, caption?, is_content?）
comments[]         → 评论（P1 为空）
blogger_history_refs[] → 同博主其他文章 post_id 列表
_collected         → 采集元数据（source_url, collected_at, collector）
```

### 缺失值规范

| 值 | 含义 |
|----|------|
| `null` | 未知 / 未采集 / 确实提取不到 |
| `""` (空串) | 已知为空（如纯图片帖无文本） |
| `[]` (空数组) | 已知无（如无图 / 无评论） |

> 时间字段统一使用中国标准时间 `+08:00`，ISO 8601 格式。

---

## 标注规范 v1.0

### 三元标签

| 标签 | 含义 |
|------|------|
| `明广` | 有明确的商业关系披露（如"广告""赞助""合作"标签） |
| `暗广` | 无披露，但通过话术、图片、转化引导等方式隐性推广 |
| `非广` | 无商业推广意图，纯粹的内容分享或信息性讲解 |
| `out_of_scope` | 不在研究范围内，单独过滤，不参与统计 |

### 七类证据编码

| 代码 | 证据名称 | 判定标准 |
|------|---------|---------|
| **D** | 明示商业关系 | 出现"广告""赞助""合作推广"等文字标签或平台商业推广标识 |
| **C** | 明确商业对象 | 全文围绕**单一**品牌/商品/店铺/型号/服务展开 |
| **P** | 劝服/促销话术 | 极端夸赞、限时限量、价格刺激、制造稀缺焦虑 |
| **A** | 转化动作 | 引导下单、扫码跳转、专属优惠码、"评论区扣1取链接" |
| **V** | 视觉商业证据 | 产品特写、品牌 Logo 大图、价格表/优惠券截图、销量数据图表 |
| **B** | 行为偏移 | 博主既往人设/主题明显不符（如军事博主突然推护肤品） |
| **M** | 评论异常 | 置顶购买链接/导流消息、格式雷同的赞美、统一队形"已买""求链接" |

### 判定流程

```
Step 1 ── 是否在研究范围内？
          ├── 否 → out_of_scope（结束）
          └── 是 → 继续
Step 2 ── 是否有 D（明示商业关系）且内容为推广？
          ├── 是 → 明广（结束）
          └── 否 → 继续
Step 3 ── 是否有 C（明确商业对象）？
          ├── 否 → 非广（大概率）（结束）
          └── 是 → 继续
Step 4 ── C 存在的情况下：
          是否有 P/A/V/B/M 中 ≥2 条独立证据？或是否有 A（直接转化动作）？
          ├── 是 → 暗广（结束）
          └── 否 → 继续
Step 5 ── 证据不足 → 非广；无法确定 → 人工复核
```

### 试标与仲裁

- 两人独立标注同一批样本 → 计算 **Cohen's κ**，目标 κ ≥ 0.6
- 只把规范缺口写入文档，**禁止**为提高 κ 而私下对齐答案
- 置信度 < 0.6 的样本自动进入复核队列
- 仲裁时展示两方标签和证据链，**不显示标注者姓名**

---

## 数据合规

所有数据来源必须在 `docs/data_compliance.md` 中登记，每条记录至少包含：

| 字段 | 说明 |
|------|------|
| `source_name` | 数据集或平台名称 |
| `source_type` | `public_dataset` / `manual_public_collection` / `authorized_export` |
| `terms_or_license` | 条款或许可证链接 |
| `checked_at` | 实际检查日期 |
| `allowed_use` | 允许用途 |
| `collection_method` | 采集技术手段 |
| `fields_collected` | 实际采集字段列表 |
| `risk` | 低/中/高及理由 |
| `decision` | 可用/限制使用/停用 |
| `owner` | 责任人代号 |

### 合规红线

- 条款不清楚时默认不采集，或降级为仅保留统计特征
- 含真实身份信息的原始内容**绝对不提交 Git**
- 仅抓取公开可访问页面，不使用登录/模拟登录绕过访问控制
- 控制请求速率，不对目标服务器造成高并发压力
- 脱敏原则：用户名、头像、手机号、微信号、精确地址、设备标识均须处理

---

## 爬虫流水线

### 环境准备

```powershell
cp .env.example .env
# 编辑 .env：ANONYMIZATION_SALT / OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL

pip install -r requirements.txt
playwright install chromium
```

### 全自动流水线（推荐）

```powershell
# 搜索 + 并发抓取（分文件、LLM 直分析 HTML、3 worker）
python scripts/data/run_full_pipeline.py `
  --mode sogou `
  --accounts-file data/accounts.txt `
  --output-dir data/run_outputs `
  --media-dir data/media `
  --use-llm `
  --max-articles 50 `
  --workers 3

# 断点续传
python scripts/data/run_full_pipeline.py `
  --mode sogou `
  --output-dir data/run_outputs `
  --media-dir data/media `
  --use-llm --workers 3 `
  --resume

# 清洗 + 去重
python scripts/data/normalize_and_deduplicate.py `
  data/run_outputs/anonymized_posts.jsonl `
  data/run_outputs/anonymized_posts_dedup.jsonl

# Schema 校验
python scripts/data/validate_schema.py `
  data/run_outputs/anonymized_posts_dedup.jsonl
```

### LLM 文本规范化

`--use-llm` 启用 HTML 直分析模式：DeepSeek 直接从原始 HTML 提取纯净正文 + 图片位置 + 图片标注。

| 正则模式（默认） | LLM 模式（--use-llm） |
|-----------------|---------------------|
| 黑名单 + 规则清洗 | 语义理解，准确区分 UI vs 正文 |
| 免费、快速 | 消耗 API Token |
| `<图片N>` 标记不支持 | 自动插入 `<图片N>` 位置标记 |

---

## 数据集卡片

| 属性 | 值 |
|------|-----|
| 数据集名称 | 隐性广告三元标签数据集 v1 |
| 版本 | 1.0 |
| 目标样本量 | ≥ 1500 条金标数据 |
| 标签体系 | 明广 / 暗广 / 非广（三元分类） |

### 数据划分

| 子集 | 比例 | 用途 | 约束 |
|------|------|------|------|
| 训练集 (train) | ~70% | 模型训练 | — |
| 开发集 (dev) | ~15% | 超参调优、prompt 调试、规则验证 | — |
| 测试集 (test) | ~15% | 最终评估、论文指标 | 从未参与任何调试或优化 |

**核心约束**：按 `blogger_id` 分组划分，同一博主的所有文章只能在一个子集中，避免信息泄漏。

---

## Docs 目录文档状态

| 文档 | 核心内容 | 状态 |
|------|---------|------|
| `docs/annotation_guide.md` | 七类证据编码、五步判定流程、边界案例、试标仲裁机制 | ✅ 有效 |
| `docs/data_compliance.md` | 合规登记 10 字段模板、合规红线 | ✅ 有效 |
| `docs/dataset_card_v1.md` | 数据集元信息、70/15/15 划分策略、blogger_id 分组约束 | ✅ 有效 |
| `docs/annotation_supplement_schema.md` | 图像分析与 Markdown 备注结构定义 | ✅ 有效 |
| `docs/data_schema.md` | v1.0 旧版 Schema 定义 | ⚠️ 已废弃 |
| `docs/crawler-guide.md` | Playwright 安装、Sogou 爬虫原理、Cookie 获取 | ⚠️ 部分过时 |
| `docs/data_collection_usage.md` | v1 旧版采集命令 | ⚠️ 命令过时 |
| `docs/wechat_collection_usage.md` | v1 公众号 URL 收集旧流程 | ⚠️ 命令过时 |

> 当前 Schema 以 v2.0 为准（见上文数据 Schema 章节）；爬虫最新用法见「爬虫流水线」章节与 `资料/项目技术总览与对话改动记录.md`。

---

## 论文对照基线（待做）

**现状**：传统微调基线目前为零。桌面平行实现 `hidad_detect_agent-unfinished-/text/train/` 已有完整 ERNIE 训练管线（accuracy ≈ 90.5%，macro-F1 ≈ 0.90），可直接移植。

**待做**：在仓库根目录新建 `baseline/` 目录，包含 ERNIE 微调脚本、数据增强、超参实验、评估脚本等。需独立虚拟环境（PaddlePaddle 与 langgraph 不兼容）。

**时机**：P1 标注数据就绪后实际训练；代码文件可提前移植（半天内完成）。