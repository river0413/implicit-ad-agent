# 隐性广告识别 · LangGraph 起步骨架

融合多模态行为特征与文本推断的隐性广告识别项目的**最小可运行起点**。
先跑通"一个图 + 一条轨迹"，再按《隐性广告识别项目_说明书.md》逐步扩成多智能体。

## 快速开始

```bash
# 1) 建虚拟环境（本机 Python 3.10，推荐 3.11+）
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash
# .venv\Scripts\activate             # Windows CMD/PowerShell

# 2) 装依赖
python -m pip install -r requirements.txt

# 3) 零成本跑通（不需要任何 Key）
python run_demo.py

# 4) 配好 .env 后，用真正的 LLM 跑（会在 LangSmith 出轨迹）
cp .env.example .env                 # 然后填入 Key
python run_demo.py --llm

# 5) 起后端服务
uvicorn app:app --reload             # 打开 http://127.0.0.1:8000/docs
```

## 看 LangSmith 轨迹
1. 去 https://smith.langchain.com 注册，拿 API Key。
2. 把 Key 填进 `.env`，确认 `LANGSMITH_TRACING=true`。
3. 运行 `python run_demo.py --llm`。
4. 打开 LangSmith → 项目 `implicit-ad-agent` → 点开最新一条 run，即可看到
   `analyze` 节点的输入/输出、LLM 调用、耗时与 token。

## 目录说明
| 路径 | 作用 |
| --- | --- |
| `impad/hello_graph.py` | 零 Key 的最小图（规则占位），验证环境与轨迹 |
| `impad/graph.py` | 真正起点：LLM 单体智能体，出判定+证据链 |
| `impad/state.py` | 图的共享状态定义 |
| `impad/llm.py` | 厂商无关 LLM 客户端（OpenAI 兼容端点） |
| `impad/config.py` | 读取 `.env` 的集中配置 |
| `app.py` | FastAPI，`POST /analyze` |
| `run_demo.py` | 一键跑样本 |
| `samples/` | 固定测试帖子 |
| `tests/` | 冒烟测试 |
