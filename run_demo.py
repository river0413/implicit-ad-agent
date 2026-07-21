"""一键跑通样本，最直观地看到"能出报告"。

用法：
    python run_demo.py                       # 零成本：规则占位图 hello_graph，不花钱、不需 Key
    python run_demo.py --llm                 # 用 .env 里的 LLM（配好 LangSmith 后能看到轨迹）
    python run_demo.py --image path/to.jpg   # 带图跑多智能体图（视觉专家；需装 requirements-vision.txt）
                                             # 可与 --llm 叠加；缺视觉依赖时视觉专家自动降级
"""
from __future__ import annotations
import json
import pathlib
import sys

# Windows 终端默认 GBK，强制 UTF-8 输出，避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _arg_value(flag: str) -> str | None:
    """取 `--flag value` 形式的参数值。"""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main():
    use_llm = "--llm" in sys.argv
    image = _arg_value("--image")

    # 带图 → 必须走多智能体图（含视觉专家）；hello_graph 无视觉能力
    if image:
        from impad.graph import graph
        print(f">> 带图分析，走多智能体图（graph.py）；图片：{image}\n")
        post = {"text": "分享一下最近入手的好物～", "blogger": "demo", "image_path": image}
        print(graph.invoke({"post": post})["report"], "\n")
        return

    samples_path = pathlib.Path(__file__).parent / "samples" / "sample_posts.json"
    samples = json.loads(samples_path.read_text(encoding="utf-8"))

    if use_llm:
        from impad.graph import graph
        print(">> 使用 LLM 图（graph.py）——请确认 .env 已配置好\n")
    else:
        from impad.hello_graph import graph
        print(">> 使用零成本占位图（hello_graph.py）\n")

    for i, post in enumerate(samples, 1):
        print(f"===== 样本 {i}：{post.get('blogger', '')} =====")
        result = graph.invoke({"post": post})
        print(result["report"], "\n")


if __name__ == "__main__":
    main()
