"""题库功能验证：哈希隔离、语义命中、跳过 AI、未命中回退。

用法：.venv/Scripts/python.exe tests/verify_qa.py
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
from app.qa.store import QAStore, parse_answer, resume_hash

RESUME_A = "简历A：后端开发，Python，RAG 系统优化"
RESUME_B = "简历B：产品经理，需求分析，用户增长"
QUESTION = "举例说明你如何制定了一个很高的目标，并最终实现它。"
PARAPHRASE = "讲讲你定过的高目标最后是怎么完成的"


class FakeTranscriber:
    def __init__(self, text: str):
        self.text = text

    def submit(self, segment):
        future: Future = Future()
        future.set_result(Transcript(self.text, Speaker.INTERVIEWER, segment.trace_id))
        return future

    def shutdown(self):
        pass


class FakeCapture:
    def __init__(self):
        self.segment_queue = queue.Queue()


class CountingLLM(BaseLLM):
    def __init__(self):
        self.calls = 0

    def answer(self, req: AnswerRequest) -> Answer:
        self.calls += 1
        return Answer(question=req.question, opener="AI 回答", points=["AI 要点"])


def main() -> int:
    QCoreApplication([])
    config = AppConfig.load()
    embedder = Embedder(config)
    failures = []

    with tempfile.TemporaryDirectory(prefix="qa_verify_") as tmp:
        store = QAStore(tmp)
        question_vec = embedder.embed([QUESTION])[0].tolist()
        store.add(RESUME_A, QUESTION,
                  "结论：我设定了远超常规的目标并达成。\n• 拆解里程碑\n• 用数据追踪",
                  tag="高目标（目的性）", vector=question_vec)

        if store.load(RESUME_B):
            failures.append("简历哈希隔离失败：B 简历看到了 A 的题库")
        if resume_hash(RESUME_A) == resume_hash(RESUME_B):
            failures.append("两份简历哈希相同")
        opener, points = parse_answer("结论句\n- 要点一\n2. 要点二")
        if opener != "结论句" or points != ["要点一", "要点二"]:
            failures.append(f"答案解析错误: {opener}, {points}")

        matcher = QAMatcher(store, embedder, threshold=config.qa_similarity_threshold)
        hit = matcher.match(RESUME_A, PARAPHRASE)
        if hit is None or hit.entry.question != QUESTION:
            failures.append(f"改写问题未命中：{None if hit is None else hit.score}")
        else:
            print(f"语义命中：{hit.score:.3f} -> {hit.entry.question}")

        if matcher.match(RESUME_A, "今天天气怎么样") is not None:
            failures.append("无关问题误命中")

        # 流水线级：命中时不得调用 LLM
        llm = CountingLLM()
        pipeline = Pipeline(config, FakeCapture(), FakeTranscriber(PARAPHRASE), llm)
        pipeline.qa_matcher = matcher   # 指向本测试的临时题库，避免读项目真实题库
        pipeline.resume_text = RESUME_A
        seen = {}
        pipeline.answer_ready.connect(lambda q, o, p, t: seen.update(question=q, opener=o, points=p))
        hits = []
        pipeline.qa_hit_ready.connect(lambda q, s, t: hits.append((q, s)))
        pipeline._handle_segment(AudioSegment(
            speaker=Speaker.INTERVIEWER, pcm=b"", trace_id="qa-verify"))
        if llm.calls != 0:
            failures.append(f"命中题库仍调用了 AI：{llm.calls} 次")
        if not hits or seen.get("opener") != "结论：我设定了远超常规的目标并达成。":
            failures.append(f"流水线回放答案异常：{hits}, {seen}")
        else:
            print(f"流水线命中：score={hits[0][1]:.3f}, AI 调用={llm.calls}, "
                  f"要点数={len(seen['points'])}")

    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("PASS: 哈希隔离 / 语义命中 / 跳过 AI / 未命中回退 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
