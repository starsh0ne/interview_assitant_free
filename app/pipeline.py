"""核心流水线：音频段 → 转写 → 说话人判断 → AI 分析 → UI 显示。

线程模型：
- 采集线程 → segment_queue
- pipeline 工作线程消费队列，提交转写 Future，等待结果
- 面试官(INTERVIEWER)提问 → 触发 AI 分析 → 通过 Qt 信号发给 UI
- 我方(SELF)回答 → 记录上下文，不触发 AI
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from concurrent.futures import Future

from PySide6.QtCore import QObject, Signal

from app.audio.capture import AudioCapture
from app.audio.transcriber import Transcriber
from app.core.config import AppConfig
from app.core.models import Answer, AudioSegment, Speaker, ThinkLevel, Transcript
from app.llm.base import AnswerRequest, BaseLLM
from app.logging_conf import bind_session_trace, get_logger, unbind_session_trace

MODULE = "pipeline"


class Pipeline(QObject):
    """QObject 提供跨线程信号，UI 线程连接信号更新界面。"""

    # 信号：转写文本（说话人, 文本, trace_id）
    transcript_ready = Signal(str, str, str)
    # 信号：AI 答案流式逐行（kind: opener|point, 文本, trace_id）
    answer_line_ready = Signal(str, str, str)
    # 信号：AI 答案就绪（问题, opener, points 字符串列表, trace_id）
    answer_ready = Signal(str, str, list, str)
    # 信号：状态变化文本
    status_changed = Signal(str)
    # 信号：错误（模块, 消息, trace_id）
    error_occurred = Signal(str, str, str)

    def __init__(self, config: AppConfig, capture: AudioCapture,
                 transcriber: Transcriber, llm: BaseLLM):
        super().__init__()
        self.config = config
        self.capture = capture
        self.transcriber = transcriber
        self.llm = llm
        self.resume_text = ""
        self.think_level: ThinkLevel = config.think_level
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._pending: list[Future] = []
        self._self_context: list[str] = []
        self._prefetched: dict[int, Future] = {}   # seg_id → 预转写 Future（未等待）
        self._log = get_logger()

    def start(self, resume_text: str, think_level: ThinkLevel) -> None:
        """启动流水线。必须在采集 start 之前调用。"""
        self.resume_text = resume_text
        self.think_level = think_level
        self._stop_event.clear()
        self._self_context = []
        self._prefetched = {}
        self._worker = threading.Thread(target=self._run, name="pipeline-worker", daemon=True)
        self._worker.start()
        self._log.info("流水线启动", module=MODULE, location="Pipeline.start",
                       status="start", think_level=think_level.value,
                       resume_len=len(resume_text))

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=5.0)
            self._worker = None
        self.transcriber.shutdown()
        self._log.info("流水线停止", module=MODULE, location="Pipeline.stop", status="success")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                segment = self.capture.segment_queue.get(timeout=0.3)
            except queue.Empty:
                continue
            bind_session_trace(segment.trace_id, location="Pipeline._run")
            try:
                self._handle_segment(segment)
            except Exception as e:
                self._log.error("流水线处理异常", module=MODULE, location="Pipeline._run",
                                status="fail", error={"type": type(e).__name__,
                                                      "message": str(e), "stack": traceback.format_exc()})
                self.error_occurred.emit(MODULE, str(e), segment.trace_id)
            finally:
                unbind_session_trace()

    def _handle_segment(self, segment: AudioSegment) -> None:
        log = get_logger()
        log.info("处理音频段", module=MODULE, location="Pipeline._handle_segment",
                 status="start", speaker=segment.speaker.value, duration_ms=segment.duration_ms,
                 is_pause=segment.is_pause, seg_id=segment.seg_id)

        # --- pause 事件：静音已 400ms，说话大概率结束——提交预转写，不阻塞等待 ---
        if segment.is_pause:
            old = self._prefetched.get(segment.seg_id)
            if old is not None and not old.done():
                # 假停顿后又停：旧转写作废但让它跑完（executor 顺序保证，结果将被覆盖）
                log.info("预转写覆盖（假停顿后再次暂停）", module=MODULE,
                         location="Pipeline._handle_segment", status="retry",
                         seg_id=segment.seg_id)
            self._prefetched[segment.seg_id] = self.transcriber.submit(segment)
            return

        # --- final 段：等预转写结果（转写已并行跑了几百 ms） ---
        prefetched: Future | None = self._prefetched.pop(segment.seg_id, None)
        if prefetched is not None:
            transcript = prefetched.result(timeout=120)
            if segment.duration_ms > transcript.duration_ms + 1200:
                # 假停顿后继续说了很多：预转写快照不完整，丢弃重转
                log.info("预转写作废（段延长）", module=MODULE, location="Pipeline._handle_segment",
                         status="retry", seg_id=segment.seg_id,
                         pause_ms=transcript.duration_ms, final_ms=segment.duration_ms)
                transcript = None
            else:
                log.info("命中预转写", module=MODULE, location="Pipeline._handle_segment",
                         status="success", seg_id=segment.seg_id,
                         prefetched_ms=transcript.duration_ms,
                         saved_wait_ms=transcript.latency_ms)
        else:
            transcript = None

        if transcript is None:
            future = self.transcriber.submit(segment)
            transcript = future.result(timeout=120)

        if not transcript.text:
            self.transcript_ready.emit(segment.speaker.value, "（未识别到语音）", segment.trace_id)
            return

        self.transcript_ready.emit(transcript.speaker.value, transcript.text, transcript.trace_id)

        if transcript.speaker == Speaker.SELF:
            # 我方回答：记录上下文，最多保留最近 3 条
            self._self_context.append(transcript.text)
            self._self_context = self._self_context[-3:]
            log.info("记录我方回答", module=MODULE, location="Pipeline._handle_segment",
                     status="success", text_len=len(transcript.text))
            return

        # 面试官提问：触发 AI 分析（流式，逐行推 UI，首条结论最快上屏）
        req = AnswerRequest(
            question=transcript.text,
            resume_text=self.resume_text,
            self_context="\n".join(self._self_context),
            think_level=self.think_level,
            trace_id=transcript.trace_id,
        )

        def on_line(kind: str, text: str):
            # Qt Signal emit 线程安全，queued connection 自动切 UI 线程
            self.answer_line_ready.emit(kind, text, transcript.trace_id)

        answer = self.llm.answer_safe_stream(req, on_line)
        self.answer_ready.emit(answer.question, answer.opener, answer.points, answer.trace_id)
