"""一键跑通样本，最直观地看到"能出报告"。

用法：
    python run_demo.py            # 零成本：用规则占位图 hello_graph，不花钱、不需 Key
    python run_demo.py --llm      # 用 .env 里的 LLM（配好 LangSmith 后会在网站看到轨迹）
"""
from __future__ import annotations
import json
import pathlib
import sys

# Windows 终端默认 GBK，强制 UTF-8 输出，避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    use_llm = True
    samples_path = pathlib.Path(__file__).parent / "samples" / "sample_posts.json"
    samples = json.loads(samples_path.read_text(encoding="utf-8"))

    if use_llm:
        try:
            from impad.llm import get_llm
            llm = get_llm()
            llm.invoke([{"role": "system", "content": "测试 LLM 是否可用"}])
            from impad.graph import graph
            print(">> 使用 LLM 图（graph.py）\n")
        except Exception as e:
            print(f">> LLM 图不可用，改用零成本占位图：{e}\n")
            from impad.hello_graph import graph
            print(">> 使用零成本占位图（hello_graph.py）\n")
        
        

    for i, post in enumerate(samples, 1):
        print(f"===== 样本 {i}：{post.get('blogger', '')} =====")
        result = graph.invoke({"post": post})
        print(result["report"], "\n")


if __name__ == "__main__":
    main()
