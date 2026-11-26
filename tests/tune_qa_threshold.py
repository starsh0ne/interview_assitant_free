"""宝洁八大问「改写表达」阈值调参。

用法：.venv/Scripts/python.exe tests/tune_qa_threshold.py
输出每条改写与原八大问的最高相似度，以及各阈值下的命中率/误命中率。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import AppConfig
from app.qa.embedder import Embedder
from app.qa.matcher import QAMatcher
from app.qa.pg8 import PG8_SAMPLES
from app.qa.store import QAStore

RESUME = "阈值调参专用简历（非真实简历）\n求职方向：后端开发\n技能：Python、RAG"

# 每条：期望命中的样例下标 + 面试官的改写表达
PARAPHRASES: list[tuple[int, str]] = [
    (0, "请分享一个你给自己设定了很高目标、最后真的实现的例子。"),
    (0, "说一次你定了个看起来很难够到的目标，你是怎么达成它的。"),
    (1, "在团队活动里，你有没有主动站出来带领大家拿到结果的经历？"),
    (1, "讲讲你主动扛责并带队达成目标的一件事。"),
    (2, "有没有一个场景，你需要先收集信息、抓住关键点，再分步推进完成任务？"),
    (2, "描述一下你通过分析信息、划重点、定步骤来达成目标的过程。"),
    (3, "你用过哪些事实和数据，让别人同意你的看法？举个具体例子。"),
    (3, "讲一次你靠事实证据说服团队达成一致。"),
    (4, "举例说明你和别人配合、一起完成一个重要目标。"),
    (4, "说个你与他人合作达成重要成果的经历。"),
    (5, "你有什么创意对项目成功起了关键作用？具体说说。"),
    (5, "讲一个你提出新点子并推动落地的例子。"),
    (6, "面对复杂局面，你如何判断关键点并集中精力解决？"),
    (6, "举例说说你评估形势后，把注意力放在核心问题上的经历。"),
    (7, "你是怎么学会一项新技能，并把它用到实际工作里的？"),
    (7, "举个你快速掌握新技能并成功实践的例子。"),
]

THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]


def main() -> int:
    config = AppConfig.load()
    embedder = Embedder(config)
    with tempfile.TemporaryDirectory(prefix="qa_tune_") as tmp:
        store = QAStore(tmp)
        vectors = embedder.embed([s["question"] for s in PG8_SAMPLES])
        ids = []
        for sample, vector in zip(PG8_SAMPLES, vectors):
            entry = store.add(RESUME, sample["question"], sample["answer"],
                              tag=sample["tag"], vector=vector.tolist())
            ids.append(entry.id)

        matcher = QAMatcher(store, embedder, threshold=0.0)
        results: list[tuple[int, float, bool]] = []
        print("改写表达命中明细（✓=命中正确题目）")
        for expected, question in PARAPHRASES:
            hit = matcher.match(RESUME, question)
            assert hit is not None
            correct = hit.entry.id == ids[expected]
            results.append((expected, hit.score, correct))
            mark = "✓" if correct else "✗"
            print(f"  {mark} {hit.score:.3f}  {PG8_SAMPLES[expected]['tag']} <- {question[:26]}")

        print("\n阈值扫描（共 16 条改写）")
        print("  阈值   正确命中   误命中   漏判")
        for threshold in THRESHOLDS:
            true_hit = sum(1 for _, score, ok in results if score >= threshold and ok)
            false_hit = sum(1 for _, score, ok in results if score >= threshold and not ok)
            miss = sum(1 for _, score, ok in results if score < threshold and ok)
            print(f"  {threshold:.2f}     {true_hit:2d}/16       {false_hit:2d}       {miss:2d}")
        print("\n建议：在「误命中=0」的前提下取正确命中最多的阈值；"
              "当前配置见 config.local.json 的 qa_similarity_threshold。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
