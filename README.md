# 隐性广告识别 · LangGraph 多智能体骨架

融合多模态行为特征与文本推断的隐性广告识别项目。
已从单体智能体扩成 **Supervisor + 专家(NLP/视觉/行为) + Judge** 的多智能体图：

```
START → Supervisor（按输入排专家队列：纯文本跳过视觉、无历史跳过行为）
          → NLP 专家（LLM；未配 Key 自动降级为规则，零成本可跑）
          → 视觉专家（占位，P2 接 OCR/图文一致性）
          → 行为专家（占位规则，P3 接 EMA+Chroma 记忆）
        → Judge（按专家可靠度加权聚合 + 低置信反思质询） → END
```

## 项目双线

| 线 | 目标 | 阶段 |
| --- | --- | --- |
| 🧠 推理线 | 多智能体识别隐性广告（Supervisor + NLP/视觉/行为 + Judge） | P2-P3 |
| 📊 数据线 | 采集 → 脱敏 → 双人标注 → 仲裁 → 金标 → 按博主划分 | P1（当前） |

> P1 里程碑：种子数据集 v1 ≥1500 条、明广/暗广/非广三元标签、Cohen's κ ≥ 0.6、三集无博主重叠。详见 [`资料/P1_数据地基与标注规范_执行指南.md`](资料/P1_数据地基与标注规范_执行指南.md)。

---

## 推理快速开始

```bash
# 1) 建虚拟环境（本机 Python 3.10，推荐 3.11+）
python -m venv .venv

# 2) 激活虚拟环境（务必先激活，否则会用到系统 Python，报 No module named 'langgraph'）
source .venv/Scripts/activate        # Windows Git Bash / macOS / Linux
# 见下方「Windows PowerShell 激活」                   # Windows PowerShell

# 3) 装依赖
python -m pip install -r requirements.txt

# 4) 零成本跑通（不需要任何 Key）
python run_demo.py

# 5) 配好 .env 后，用真正的 LLM 跑（会在 LangSmith 出轨迹）
cp .env.example .env                 # 然后填入 Key
python run_demo.py --llm

# 6) 起后端服务
uvicorn app:app --reload             # 打开 http://127.0.0.1:8000/docs
```

---

## 数据采集快速开始

### 环境准备

```bash
# Playwright 浏览器依赖（微信爬虫需要）
python -m playwright install chromium

# 国内镜像加速
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/"
python -m playwright install chromium
```

### 一键全流程

```bash
# 从公众号名称列表 → 抓取 URL → 内容脱敏 → 去重 → Schema 校验
python scripts/data/run_full_pipeline.py --mode sogou --accounts-file data/accounts.txt --output-dir data/run_outputs

# 从单篇微信文章出发
python scripts/data/run_full_pipeline.py --mode article --source "https://mp.weixin.qq.com/s/..." --output-dir data/run_outputs
```

### 分步执行

```bash
# 步骤 1：搜索公众号文章 URL
python scripts/data/sogou_wechat_crawler.py --account "公众号名" --max-articles 50 --output data/run_outputs/urls.txt

# 步骤 2：抓取内容 + 匿名化（需在 .env 中设置 ANONYMIZATION_SALT）
python scripts/data/crawl_public_posts.py --input data/run_outputs/urls.txt --output data/run_outputs/anonymized_posts.jsonl --collector D

# 步骤 3：规范化 + 去重
python scripts/data/normalize_and_deduplicate.py data/run_outputs/anonymized_posts.jsonl data/run_outputs/anonymized_posts_dedup.jsonl

# 步骤 4：Schema 校验
python scripts/data/validate_schema.py data/run_outputs/anonymized_posts_dedup.jsonl
```

---

## 标注与金标构建

```bash
# 计算双人标注一致性（Cohen's κ + 混淆矩阵 + 分歧详情）
python scripts/data/calculate_agreement.py ann_D.jsonl ann_N.jsonl

# 合并双人标注 + 仲裁记录 → 金标数据集
python scripts/data/build_gold_dataset.py ann_D.jsonl ann_N.jsonl adjudication.jsonl gold_v1.jsonl

# 按 blogger_id 分组划分 train/dev/test（7:1.5:1.5，防同博主泄漏）
python scripts/data/split_by_blogger.py gold_v1.jsonl data/splits/train_ids.txt data/splits/dev_ids.txt data/splits/test_ids.txt
```

### Windows PowerShell 激活（踩坑指南）

PowerShell 的激活脚本是 `Activate.ps1`（不是 `activate`）：

```powershell
.venv\Scripts\Activate.ps1
```

- 若报「无法加载 …… 未数字签名 / 禁止运行脚本」，是执行策略拦的。**当前窗口临时放行一次**（只影响这个窗口，安全）：
  ```powershell
  Set-ExecutionPolicy -Scope Process RemoteSigned
  ```
  再执行 `.venv\Scripts\Activate.ps1`。激活成功后命令行前面会出现 `(.venv)`。
- 验证用对了 Python：`where.exe python`，第一行应指向 `...\implicit-ad-agent\.venv\Scripts\python.exe`。
- **不想激活也行**，直接点名 venv 的 python 即可：
  ```powershell
  .venv\Scripts\python.exe run_demo.py
  ```

> `No module named 'langgraph'` = 没激活 venv、命令跑到系统 Python 上了。依赖装在 venv 里，先激活或用上面的点名方式。

## 看 LangSmith 轨迹
1. 去 https://smith.langchain.com 注册，拿 API Key。
2. 把 Key 填进 `.env`，确认 `LANGSMITH_TRACING=true`。
3. 运行 `python run_demo.py --llm`。
4. 打开 LangSmith → 项目 `implicit-ad-agent` → 点开最新一条 run，即可看到
   supervisor / nlp / judge 等各节点的输入输出、LLM 调用、耗时与 token。

## 目录说明

### 🧠 推理引擎
| 路径 | 作用 |
| --- | --- |
| `impad/hello_graph.py` | 零 Key 的最小图（规则占位），验证环境与轨迹 |
| `impad/graph.py` | 多智能体图的装配（只搭骨架，不写业务逻辑） |
| `impad/agents/supervisor.py` | 主控调度：按输入决定派哪些专家 + 条件路由 |
| `impad/agents/nlp_agent.py` | NLP 专家：LLM 判意图/话术，无 Key 自动降级规则 |
| `impad/agents/vision_agent.py` | 视觉专家（占位，P2 接 OCR/图文一致性） |
| `impad/agents/behavior_agent.py` | 行为专家（占位规则，P3 接 EMA+Chroma） |
| `impad/agents/judge.py` | 加权聚合投票 + 低置信反思质询 |
| `impad/tools/keywords.py` | 广告信号关键词清单（规则降级共用） |
| `impad/state.py` | 图的共享状态定义（plan / agent_votes / evidence …） |
| `impad/llm.py` | 厂商无关 LLM 客户端（OpenAI 兼容端点） |
| `impad/config.py` | 读取 `.env` 的集中配置 |
| `app.py` | FastAPI，`POST /analyze`（返回含各专家投票） |
| `run_demo.py` | 一键跑推理 Demo |

### 📊 数据工具链（P1）
| 路径 | 作用 |
| --- | --- |
| `scripts/data/run_full_pipeline.py` | 一键全流程：抓取 URL → 脱敏 → 去重 → 校验，支持单/批量公众号 |
| `scripts/data/sogou_wechat_crawler.py` | Playwright 搜狗微信爬虫，按公众号名搜索、解析加密跳转链接 |
| `scripts/data/crawl_wechat_account.py` | requests 版搜狗微信搜索（轻量），按公众号名检索文章 URL |
| `scripts/data/crawl_wechat_from_article.py` | 从单篇文章 URL 推断 `__biz` 抓取该号历史文章，支持 Playwright + cookies |
| `scripts/data/crawl_public_posts.py` | 公开内容采集 + 脱敏（SHA-256 匿名 ID、模糊化博主名），输出 JSONL |
| `scripts/data/normalize_and_deduplicate.py` | 文本规范化（去 URL/@/#）+ SHA-256 指纹去重 |
| `scripts/data/validate_schema.py` | Schema 校验，检查必填字段与格式合规 |
| `scripts/data/build_gold_dataset.py` | 合并双人标注 + 仲裁 → 金标数据集 |
| `scripts/data/split_by_blogger.py` | 按 blogger_id 分组切分 train/dev/test（7:1.5:1.5） |
| `scripts/data/calculate_agreement.py` | Cohen's κ + 95% bootstrap CI + 混淆矩阵 + 分歧详情 |

### 📖 规范与文档
| 路径 | 作用 |
| --- | --- |
| `docs/data_compliance.md` | 数据合规登记：来源、条款检查、采集边界、风险评估 |
| `docs/data_schema.md` | 数据 Schema v1.0：内容记录与标注记录字段定义 |
| `docs/annotation_guide.md` | 标注规范 v1.0：三元判定、7 类证据编码、判定流程、边界案例 |
| `docs/dataset_card_v1.md` | 数据集卡片：≥1500 条目标、划分策略、伦理说明 |
| `docs/data_collection_usage.md` | `crawl_public_posts.py` 使用说明 |
| `docs/wechat_collection_usage.md` | `crawl_wechat_account.py` 使用说明 |
| `docs/crawler-guide.md` | Playwright 爬虫环境配置（Chromium 安装、国内镜像） |
| `资料/P1_数据地基与标注规范_执行指南.md` | P1 四周执行路线、分工、验收检查表 |

### 其他
| 路径 | 作用 |
| --- | --- |
| `samples/` | 固定测试帖子 |
| `tests/` | 冒烟测试 + 多智能体路由/聚合测试（全部零 Key） |
| `data/` | 原始数据(raw)、中间产物(interim)、标注(annotations)、划分(splits)、运行输出(run_outputs) |
