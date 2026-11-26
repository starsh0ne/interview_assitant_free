"""回归验证：A+C 多轮对话历史。

覆盖三件事：
1. 窗口规则：第 1 问 0 轮、第 2 问 1 轮、第 3 问起固定 2 轮（且滚动淘汰最旧的）
2. 题库命中那一轮的 Q/A 也进历史（C 方案）
3. DeepSeek 的 messages 序列 = system + 交替 user/assistant 历史 + 当前 user

运行：.venv/Scripts/python.exe tests/verify_multiturn.py
"""
from __future__ import annotations

import queue
import sys
import tempfile
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication

from app.audio.capture import AudioCapture
from app.core.config import AppConfig
from app.core.models import Answer, AudioSegment, Speaker, Transcript, ThinkLevel
from app.llm.base import AnswerRequest, BaseLLM
from app.llm.deepseek import DeepSeekLLM
from app.pipeline import Pipeline
from app.qa.embedder import Embedder
from app.qa.matcher import QAMatcher
from app.qa.store import QAStore

RESUME = "后端开发 / Python / RAG 检索优化 / 主导高并发改造 QPS 1000→5000"
QA_Q = "举例说明你如何制定了一个很高的目标，并最终实现它。"
QA_A_OPENER = "结论：我设定了远超常规的目标并达成。"
QA_A_POINTS = ["把目标拆成三个里程碑", "上线后 QPS 从 1000 提升到 5000"]


class FakeTranscriber:
    def __init__(self):
        self.text = ""

    def submit(self, segment):
        f: Future = Future()
        f.set_result(Transcript(self.text, Speaker.INTERVIEWER, segment.trace_id))
        return f

    def shutdown(self):
        pass


class FakeCapture:
    def __init__(self):
        self.segment_queue = queue.Queue()


class RecordingLLM(BaseLLM):
    """记录每次请求拿到的历史快照，返回可识别的答案文本。"""

    def __init__(self):
        self.history_snapshots: list[list[dict]] = []
        self.calls = 0

    def answer(self, req: AnswerRequest) -> Answer:
        self.calls += 1
        self.history_snapshots.append([dict(m) for m in req.history])
        return Answer(
            question=req.question,
            opener=f"AI结论{self.calls}",
            points=[f"AI要点{self.calls}"],
        )


def _ask(pipeline: Pipeline, transcriber: FakeTranscriber, question: str, trace: str) -> None:
    transcriber.text = question
    pipeline._handle_segment(AudioSegment(
        speaker=Speaker.INTERVIEWER, pcm=b"", trace_id=trace))


def _summary(history: list[dict]) -> str:
    return " | ".join(f"{m['role'][0].upper()}:{m['content'][:14]}" for m in history)


def check_window(config: AppConfig) -> list[str]:
    """窗口规则：0 / 1 / 2 / 2 轮，且第 4 问淘汰最旧的一轮。"""
    failures = []
    cfg = AppConfig.load()
    cfg.qa_enabled = False   # 纯 AI 路径，排除题库干扰
    tr = FakeTranscriber()
    llm = RecordingLLM()
    p = Pipeline(cfg, FakeCapture(), tr, llm)
    p.start(RESUME, ThinkLevel.LOW)
    questions = ["问题一", "问题二", "问题三", "问题四"]
    for i, q in enumerate(questions):
        _ask(p, tr, q, f"win-{i}")

    expected = [
        [],
        ["U:问题一", "A:AI结论1\nAI要点1"],
        ["U:问题一", "A:AI结论1\nAI要点1", "U:问题二", "A:AI结论2\nAI要点2"],
        ["U:问题二", "A:AI结论2\nAI要点2", "U:问题三", "A:AI结论3\nAI要点3"],
    ]
    for i, exp in enumerate(expected):
        got = llm.history_snapshots[i]
        got_pairs = [f"{m['role'][0].upper()}:{m['content']}" for m in got]
        print(f"  第{i+1}问历史 {len(got)//2} 轮: {_summary(got)}")
        if got_pairs != exp:
            failures.append(f"第{i+1}问历史不符：期望 {exp}，实际 {got_pairs}")
    p.stop()
    return failures


def check_qa_in_history(config: AppConfig, embedder: Embedder) -> list[str]:
    """题库命中轮的 Q/A 进历史，下一轮追问能拿到。"""
    failures = []
    with tempfile.TemporaryDirectory(prefix="mt_verify_") as tmp:
        store = QAStore(tmp)
        store.add(RESUME, QA_Q, f"{QA_A_OPENER}\n- {QA_A_POINTS[0]}\n- {QA_A_POINTS[1]}",
                  vector=embedder.embed([QA_Q])[0].tolist())
        matcher = QAMatcher(store, embedder, threshold=config.qa_similarity_threshold)

        cfg = AppConfig.load()
        cfg.qa_enabled = True
        tr = FakeTranscriber()
        llm = RecordingLLM()
        p = Pipeline(cfg, FakeCapture(), tr, llm)
        p.qa_matcher = matcher
        p.start("速查卡", ThinkLevel.LOW, qa_resume_text=RESUME)

        paraphrase = "讲讲你定过的高目标最后是怎么完成的"
        _ask(p, tr, paraphrase, "qa-hit")
        print(f"  题库命中后 AI 调用数={llm.calls}, 历史={_summary(p._qa_history)}")
        if llm.calls != 0:
            failures.append(f"题库命中仍调用 AI：{llm.calls}")
        if len(p._qa_history) != 2:
            failures.append(f"题库命中未写入历史：{p._qa_history}")
        elif (p._qa_history[0]["role"] != "user"
              or p._qa_history[0]["content"] != paraphrase
              or QA_A_OPENER not in p._qa_history[1]["content"]):
            failures.append(f"题库历史内容错误：{p._qa_history}")

        # 第 2 问：指代型追问，未命中题库 → 走 AI，但应带着题库那轮历史
        followup = "上个问题你提到那个目标，请详细介绍下你是怎么拆解的？"
        _ask(p, tr, followup, "qa-followup")
        if llm.calls != 1:
            failures.append(f"追问未走 AI：{llm.calls}")
        elif len(llm.history_snapshots[0]) != 2:
            failures.append(f"追问没带题库历史：{llm.history_snapshots[0]}")
        else:
            print(f"  追问携带历史: {_summary(llm.history_snapshots[0])}")
        p.stop()
    return failures


def check_messages(config: AppConfig) -> list[str]:
    """DeepSeek 实际发出的 messages 序列。用假 client 拦截，不发真实请求。"""
    failures = []
    captured: dict = {}

    class FakeStream:
        def __iter__(self):
            return iter([
                SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="结论句"))]),
                SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="\n要点句"))]),
            ])

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeStream()

    cfg = AppConfig.load()
    cfg.deepseek_api_key = "test-key-not-real"
    llm = DeepSeekLLM(cfg)
    llm.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions()))

    history = [
        {"role": "user", "content": "请介绍你的项目"},
        {"role": "assistant", "content": "结论：我做过 RAG 优化\n上线后延迟下降"},
    ]
    req = AnswerRequest(question="上个问题你提到的 RAG，具体怎么做的？",
                        resume_text="候选人速查卡", history=history)
    llm.answer(req)

    msgs = captured.get("messages", [])
    roles = [m["role"] for m in msgs]
    print(f"  messages roles: {roles}")
    if roles != ["system", "user", "assistant", "user"]:
        failures.append(f"messages 角色序列错误：{roles}")
    if msgs[1:3] != history:
        failures.append(f"历史未按顺序注入：{msgs[1:3]}")
    if "RAG" not in msgs[-1]["content"] or "候选人速查卡" not in msgs[-1]["content"]:
        failures.append(f"当前 user prompt 内容错误：{msgs[-1]['content'][:80]}")
    if "多轮衔接" not in msgs[0]["content"]:
        failures.append("system prompt 缺少多轮衔接说明")
    return failures


def main() -> int:
    QCoreApplication([])
    config = AppConfig.load()
    embedder = Embedder(config)
    failures = []

    print("== 窗口规则 ==")
    failures += check_window(config)
    print("== 题库入历史 ==")
    failures += check_qa_in_history(config, embedder)
    print("== messages 序列 ==")
    failures += check_messages(config)

    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("PASS: 0/1/2 轮窗口 / 淘汰最旧 / 题库入历史 / 真多轮 messages 序列")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
