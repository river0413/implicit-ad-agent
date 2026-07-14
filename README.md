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
uvicorn app:app --reload             # 打开 http://127.0.0.1:8000/docs
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
| `impad/agents/vision_agent.py` | 视觉专家（占位，P2 接 OCR/图文一致性） |
| `impad/agents/behavior_agent.py` | 行为专家（占位规则，P3 接 EMA+Chroma） |
| `impad/agents/judge.py` | 加权聚合投票 + 低置信反思质询 |
| `impad/tools/keywords.py` | 广告信号关键词清单（规则降级共用） |
| `impad/state.py` | 图的共享状态定义（plan / agent_votes / evidence …） |
| `impad/llm.py` | 厂商无关 LLM 客户端（OpenAI 兼容端点） |
| `impad/config.py` | 读取 `.env` 的集中配置 |
| `app.py` | FastAPI，`POST /analyze`（返回含各专家投票） |
| `run_demo.py` | 一键跑样本 |
| `samples/` | 固定测试帖子 |
| `tests/` | 冒烟测试 + 多智能体路由/聚合测试（全部零 Key） |
