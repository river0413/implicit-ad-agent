# 隐性广告识别 · LangGraph 多智能体骨架

融合多模态行为特征与文本推断的隐性广告识别项目。
已从单体智能体扩成 **Supervisor + 专家(NLP/视觉/行为) + Judge** 的多智能体图：

```
START → Supervisor（按输入排专家队列：纯文本跳过视觉、无历史跳过行为）
          → NLP 专家（LLM；未配 Key 自动降级为规则，零成本可跑）
          → 视觉专家（YOLO11 物体检测 + OCR 抠图内文字回灌关键词 + 加权焦点；未装依赖自动降级）
          → 行为专家（占位规则，P3 接 EMA+Chroma 记忆）
        → Judge（按专家可靠度加权聚合 + 低置信反思质询） → END
```

## 快速开始

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
python -m uvicorn app:app --reload   # 打开 http://127.0.0.1:8000/docs
# ↑ 用 "python -m uvicorn" 而不是直接 "uvicorn"：
#   Windows 的 .venv\Scripts\uvicorn.exe 会把 Python 路径硬编码进去，
#   路径含中文或 venv 被移动过时 launcher 会报 "Fatal error in launcher"。
#   python -m uvicorn 完全绕过这个 exe，效果一样。pip/pytest 同理用 python -m pip/pytest。
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
| 路径 | 作用 |
| --- | --- |
| `impad/hello_graph.py` | 零 Key 的最小图（规则占位），验证环境与轨迹 |
| `impad/graph.py` | 多智能体图的装配（只搭骨架，不写业务逻辑） |
| `impad/agents/supervisor.py` | 主控调度：按输入决定派哪些专家 + 条件路由 |
| `impad/agents/nlp_agent.py` | NLP 专家：LLM 判意图/话术，无 Key 自动降级规则 |
| `impad/agents/vision_agent.py` | 视觉专家：物体检测 + OCR 抠图内文字回灌关键词 + 焦点；缺依赖自动降级 |
| `impad/agents/behavior_agent.py` | 行为专家（占位规则，P3 接 EMA+Chroma） |
| `impad/agents/judge.py` | 加权聚合投票 + 低置信反思质询 |
| `impad/tools/keywords.py` | 广告信号关键词清单 + 6 维可解释特征（`compute_keyword_weights`） |
| `impad/tools/vision.py` | YOLO11 + EasyOCR + 焦点（重依赖惰性导入，`vision_available()` 探测） |
| `impad/state.py` | 图的共享状态定义（plan / agent_votes / keyword_weights / vision_findings …） |
| `impad/llm.py` | 厂商无关 LLM 客户端（OpenAI 兼容端点） |
| `impad/config.py` | 读取 `.env` 的集中配置 |
| `app.py` | FastAPI，`POST /analyze`（返回含各专家投票） |
| `run_demo.py` | 一键跑样本；`--image path` 带图分析 |
| `samples/` | 固定测试帖子 + `images/` 测试图 |
| `requirements-vision.txt` | 视觉专家的可选重依赖（不装则视觉自动降级） |
| `tests/` | 冒烟测试 + 多智能体路由/聚合/关键词特征/视觉降级测试（全部零 Key、零重依赖） |

## 6 维可解释特征（keyword_weights）

每次分析都会附带一份**确定性**的 6 维关键词权重向量（0~1），无需 LLM、零成本可算：

| 维度（英文字段） | 含义 |
| --- | --- |
| `promotion_words` | 促销种草话术 |
| `price_mentions` | 价格 / 优惠提及 |
| `urgency_expressions` | 紧迫 / 稀缺感 |
| `brand_mentions` | 品牌 / 商务合作 |
| `action_words` | 行动召唤（引流下单/扫码/链接） |
| `natural_expression` | 自然表达 / 生活分享（暗广的"外壳"，作反向信号） |

用途：① Judge 聚合时多一路证据；② NLP 规则降级里当"未命中软广词但整体像带货"的兜底判据（`ad_pressure`）；③ 前端可画雷达图、论文可解释性分析。
它出现在 `/analyze` 响应的 `keyword_weights` 字段、各专家投票与证据链里。计算逻辑见 `impad/tools/keywords.py`。

## 视觉专家（可选，需装重依赖）

视觉专家给帖子配图做三件事：**物体检测**（YOLO11，80 类）、**OCR 文字识别**（EasyOCR 中英文）、**加权焦点**。
最关键的是 OCR：暗广常把广告词印在图上（"扫码领券""第二件半价"），文本专家看不到——
视觉专家把图里的文字抠出来**回灌关键词规则**，命中即形成视觉侧证据与投票。

```bash
# 1) 装可选重依赖（约 2~3GB；首次运行自动下载 YOLO ~5MB、OCR 模型 ~100MB）
python -m pip install -r requirements-vision.txt

# 2) 带图跑多智能体图
python run_demo.py --image samples/images/test_image.jpg

# 3) API：POST /analyze 的请求体加一个可选字段
#    {"text": "分享个好物～", "image_path": "samples/images/test_image.jpg"}
```

**不装也没关系**：`vision_agent` 探测到依赖缺失会自动投空票（`confidence=0`，Judge 忽略），
全部现有功能与测试照常。判定逻辑 `vote_from_findings` 是纯函数，因此视觉测试零重依赖也能跑。
> 注：为保持轻量，移植时**未搬**桌面版的标注绘图（画框图）功能——智能体只需结构化结果；
> 将来 P5 前端要展示带框图时再单独加。

## 论文对照基线（待做：块③）

**现状**：主线项目里传统微调基线这块目前是零。  
**来源**：桌面平行实现 `hidad_detect_agent-unfinished--main/text/train/` 已有完整的 ERNIE 训练管线，
并跑出了实测结果（accuracy ≈ 90.5%，macro-F1 ≈ 0.90），可直接移植。

**待做内容**：
1. 在仓库根目录新建 `baseline/` 目录（与 `implicit-ad-agent/` 平级），内含：
   - `train/hidden_ad_train_v2.py`：ERNIE 微调主脚本（PaddlePaddle 生态）
   - `train/build_balanced_dataset.py`：LLM 辅助构建三类平衡数据集（P1 阶段 D 可直接用）
   - `train/augment_hidden_ad.py`：中文数据增强（分句重排/同义词/emoji 扰动）
   - `train/test_training_methods_v2.py`：54 组超参网格实验（early stopping/warmup/标签平滑）
   - `train/evaluate_model.py`：P/R/F1/混淆矩阵评估
   - `inference_service.py`：训练后模型的推理封装（未来可接进 Judge 当一票）
   - `benchmarks/`：桌面版已跑出的两份 benchmark JSON（论文参考数据，acc≈90.5%）
   - `requirements.txt`：`paddlepaddle + paddlenlp + sklearn + tqdm`（独立 venv，勿与主线混用）
   - `README.md`：说明这是论文对照用、如何建环境、如何跑

2. **独立虚拟环境**（必须，PaddlePaddle 与 langgraph 依赖不兼容）：
   ```powershell
   cd baseline
   python -m venv .venv-baseline
   .venv-baseline\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

**时机**：等 P1 标注数据就绪后再实际训练；移植代码文件本身可提前做（搬文件 + 写 README，半天内完成）。  
**负责人建议**：D（王一帆）主导，数据集构建脚本正是 P1 需要的工具。

1.工程性论文定题！！
2.研究型论文定题：（8/16前提交） 纲要，关键词，目录，综述，......
人员分工
研究型论文的要求：提出假设，证明观点，算法相关（深度学习，评估与论证模型）
3.查阅MMM2024-2026历年论文(微信群)，尽量大创相关论文
4.若2不行，【Flow Us息流】（微信群）论题五选一
5.endnotes：导入论文pdf原文