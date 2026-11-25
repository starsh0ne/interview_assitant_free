"""端到端流水线测试：Mock 转写 + Mock LLM，验证双源路由与信号。

不依赖真实麦克风/网络，可在 CI 运行。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication

from app.audio.capture import AudioCapture
from app.audio.transcriber import Transcriber
from app.core.config import AppConfig
from app.core.models import Answer, AudioSegment, Speaker, ThinkLevel, Transcript
from app.llm.base import AnswerRequest, BaseLLM
from app.logging_conf import configure_logging
from app.pipeline import Pipeline


class MockTranscriber(Transcriber):
    def __init__(self, config):
        self.config = config
        self._log = None

    def submit(self, segment: AudioSegment):
        from concurrent.futures import Future
        f = Future()
        text = "请介绍一下你自己" if segment.speaker == Speaker.INTERVIEWER else "我叫张三，做后端开发"
        f.set_result(Transcript(text=text, speaker=segment.speaker,
                                trace_id=segment.trace_id, duration_ms=1000, latency_ms=10))
        return f

    def shutdown(self):
        pass


class MockLLM(BaseLLM):
    name = "mock"

    def answer(self, req: AnswerRequest) -> Answer:
        assert req.think_level == ThinkLevel.LOW
        assert "张三" in req.resume_text
        return Answer(question=req.question, opener="我叫张三",
                      points=["第一点", "第二点", "第三点"])


def main():
    configure_logging()
    app = QCoreApplication(sys.argv)
    config = AppConfig.load()

    capture = AudioCapture(config)
    pipeline = Pipeline(config, capture, MockTranscriber(config), MockLLM())

    transcripts = []
    answers = []

    pipeline.transcript_ready.connect(lambda sp, tx, tid: transcripts.append((sp, tx, tid)))
    pipeline.answer_ready.connect(lambda q, op, pts, tid: answers.append((q, op, pts, tid)))

    pipeline.start("张三的简历", ThinkLevel.LOW)

    # 投递两段：我方回答 + 面试官提问
    cap = capture.segment_queue
    cap.put(AudioSegment(speaker=Speaker.SELF, pcm=b"\x00\x00" * 100,
                         trace_id="e2e-001", duration_ms=1000))
    cap.put(AudioSegment(speaker=Speaker.INTERVIEWER, pcm=b"\x00\x00" * 100,
                         trace_id="e2e-002", duration_ms=1000))

    deadline = time.time() + 8
    while len(answers) < 1 and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)

    pipeline.stop()

    assert len(transcripts) == 2, f"应有 2 条转写，实际 {len(transcripts)}"
    assert any(sp == "self" for sp, _, _ in transcripts), "缺我方转写"
    assert len(answers) == 1, f"应有 1 个 AI 回答（仅面试官触发），实际 {len(answers)}"
    q, op, pts, tid = answers[0]
    assert q == "请介绍一下你自己" and op == "我叫张三" and len(pts) == 3
    assert tid == "e2e-002", f"trace_id 未贯穿: {tid}"
    print("端到端流水线测试通过：双源路由正确、trace_id 贯穿、仅面试官触发 AI")


if __name__ == "__main__":
    main()
