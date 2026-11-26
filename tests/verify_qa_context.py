"""回归验证：AI 上下文用速查卡、题库哈希用简历全文，二者不能混用。

历史 bug：main.py 把速查卡传给 pipeline.start() 当 resume_text，
题库按简历全文哈希隔离 → 查不到任何条目 → 题库永远不命中。

运行：.venv/Scripts/python.exe tests/verify_qa_context.py
"""
from __future__ import annotations

import queue
import sys
import tempfile
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication

from app.audio.capture import AudioCapture
from app.core.config import AppConfig
from app.core.models import Answer, AudioSegment, Speaker, Transcript, ThinkLevel
from app.llm.base import AnswerRequest, BaseLLM
from app.pipeline import Pipeline
from app.qa.embedder import Embedder
from app.qa.matcher import QAMatcher
from app.qa.store import QAStore, resume_hash

FULL_RESUME = "简历全文：后端开发 / Python / RAG 检索优化 / 主导高并发改造 QPS 1000→5000"
AI_CARD = "测试候选人 · 后端 · 5 年 · RAG"   # 模拟速查卡：与全文完全不同的文本
QUESTION = "举例说明你如何制定了一个很高的目标，并最终实现它。"
PARAPHRASE = "讲讲你定过的高目标最后是怎么完成的"


class FakeTranscriber:
    def __init__(self, text: str):
        self.text = text

    def submit(self, segment):
        f: Future = Future()
        f.set_result(Transcript(self.text, Speaker.INTERVIEWER, segment.trace_id))
        return f

    def shutdown(self):
        pass


class FakeCapture:
    def __init__(self):
        self.segment_queue = queue.Queue()


class CountingLLM(BaseLLM):
    def __init__(self):
        self.calls = 0
        self.last_resume_text = ""

    def answer(self, req: AnswerRequest) -> Answer:
        self.calls += 1
        self.last_resume_text = req.resume_text
        return Answer(question=req.question, opener="AI 回答", points=["AI 要点"])


def main() -> int:
    QCoreApplication([])
    config = AppConfig.load()
    embedder = Embedder(config)
    failures = []

    # 哈希必须不同，否则本测试无意义
    if resume_hash(FULL_RESUME) == resume_hash(AI_CARD):
        failures.append("测试文本设计错误：全文与速查卡哈希相同")

    with tempfile.TemporaryDirectory(prefix="qa_ctx_verify_") as tmp:
        store = QAStore(tmp)
        store.add(FULL_RESUME, QUESTION,
                  "结论：我设定了远超常规的目标并达成。\n• 拆解里程碑",
                  vector=embedder.embed([QUESTION])[0].tolist())
        matcher = QAMatcher(store, embedder, threshold=config.qa_similarity_threshold)

        # 关键场景：AI 用速查卡，题库用全文
        llm = CountingLLM()
        pipeline = Pipeline(config, FakeCapture(), FakeTranscriber(PARAPHRASE), llm)
        pipeline.qa_matcher = matcher
        pipeline.start(AI_CARD, ThinkLevel.LOW, qa_resume_text=FULL_RESUME)

        hits = []
        seen = {}
        pipeline.qa_hit_ready.connect(lambda q, s, t: hits.append((q, s)))
        pipeline.answer_ready.connect(
            lambda q, o, p, t: seen.update(question=q, opener=o, points=p))
        pipeline._handle_segment(AudioSegment(
            speaker=Speaker.INTERVIEWER, pcm=b"", trace_id="ctx-verify"))

        if not hits:
            failures.append("速查卡上下文 + 全文字题库 → 未命中（bug 复现）")
        elif hits[0][1] < config.qa_similarity_threshold:
            failures.append(f"命中分数异常：{hits[0][1]}")
        else:
            print(f"命中：score={hits[0][1]:.3f} · 原题={hits[0][0]}")

        if llm.calls != 0:
            failures.append(f"命中题库仍调用 AI：{llm.calls} 次")
        if seen.get("opener") != "结论：我设定了远超常规的目标并达成。":
            failures.append(f"回放答案错误：{seen}")

        # 未命中场景：AI 应拿到速查卡而非全文
        fake2 = FakeTranscriber("今天天气怎么样")
        llm2 = CountingLLM()
        p2 = Pipeline(config, FakeCapture(), fake2, llm2)
        p2.qa_matcher = matcher
        p2.start(AI_CARD, ThinkLevel.LOW, qa_resume_text=FULL_RESUME)
        p2._handle_segment(AudioSegment(
            speaker=Speaker.INTERVIEWER, pcm=b"", trace_id="ctx-verify-2"))
        if llm2.calls != 1:
            failures.append(f"未命中时 AI 调用异常：{llm2.calls} 次")
        elif llm2.last_resume_text != AI_CARD:
            failures.append(f"AI 上下文用错：期望速查卡，实际={llm2.last_resume_text[:30]}")

        pipeline.stop()
        p2.stop()

    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("PASS: 全文查题库命中 / 速查卡给 AI / 命中零 AI 调用 / 未命中回退")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
