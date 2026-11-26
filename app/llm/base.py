"""大模型通用接口。

设计目标：接入新模型只需实现本基类，pipeline/UI 不感知具体厂商。
"""
from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.models import Answer, ThinkLevel
from app.logging_conf import get_logger

MODULE = "llm"


@dataclass
class AnswerRequest:
    """一次回答生成请求。"""
    question: str
    resume_text: str = ""
    self_context: str = ""        # 我方此前口述的上下文（可选）
    think_level: ThinkLevel = ThinkLevel.LOW
    trace_id: str = ""
    history: list[dict] = field(default_factory=list)  # 近 N 轮 [{"role":"user"/"assistant","content":...}]


class BaseLLM(ABC):
    """所有 LLM 实现必须继承此类。"""

    name: str = "base"

    @abstractmethod
    def answer(self, req: AnswerRequest) -> Answer:
        """根据问题与简历上下文生成要点式回答。同步方法（pipeline 在线程池调用）。"""
        ...

    def answer_stream(self, req: AnswerRequest, on_line) -> Answer:
        """流式版本：每解析出一行就回调 on_line(kind, text)。

        kind: "opener"（首行结论）| "point"（后续要点行）。
        返回完整 Answer。默认实现降级为非流式后逐行回调，
        支持流式的实现（如 DeepSeek）重写此方法获得真实流式体验。
        """
        result = self.answer(req)
        if result.opener:
            on_line("opener", result.opener)
        for p in result.points:
            on_line("point", p)
        return result

    def answer_safe_stream(self, req: AnswerRequest, on_line) -> Answer:
        """流式入口：统一日志与降级。pipeline 调用此方法。"""
        log = get_logger()
        start = time.perf_counter()
        log.info("AI 分析开始", module=MODULE, location=f"{self.name}.answer_stream",
                 status="start", think_level=req.think_level.value,
                 question_len=len(req.question), resume_len=len(req.resume_text),
                 history_turns=len(req.history) // 2)
        try:
            result = self.answer_stream(req, on_line)
            result.latency_ms = int((time.perf_counter() - start) * 1000)
            result.think_level = req.think_level.value
            result.trace_id = req.trace_id
            log.info("AI 分析完成", module=MODULE, location=f"{self.name}.answer_stream",
                     status="success", duration_ms=result.latency_ms,
                     points_count=len(result.points))
            return result
        except Exception as e:
            log.error("AI 分析失败", module=MODULE, location=f"{self.name}.answer_stream",
                      status="fail", error={
                          "type": type(e).__name__,
                          "message": str(e),
                          "stack": traceback.format_exc(),
                      })
            fallback = Answer(
                question=req.question,
                opener="（AI 分析失败，自行作答提示）",
                points=["先一句话给结论，再分两点展开", "结合简历里的项目数字最有说服力"],
                trace_id=req.trace_id,
                think_level=req.think_level.value,
            )
            on_line("opener", fallback.opener)
            for p in fallback.points:
                on_line("point", p)
            return fallback

    def warmup(self) -> None:
        """连接预热：点开始时后台调用，消除首次请求的建连开销。默认空实现。"""
        return None

    def answer_safe(self, req: AnswerRequest) -> Answer:
        """带统一日志与异常包装的调用入口。pipeline 应调用此方法而非直接 answer。"""
        log = get_logger()
        start = time.perf_counter()
        log.info("AI 分析开始", module=MODULE, location=f"{self.name}.answer",
                 status="start", think_level=req.think_level.value,
                 question_len=len(req.question), resume_len=len(req.resume_text))
        try:
            result = self.answer(req)
            result.latency_ms = int((time.perf_counter() - start) * 1000)
            result.think_level = req.think_level.value
            result.trace_id = req.trace_id
            log.info("AI 分析完成", module=MODULE, location=f"{self.name}.answer",
                     status="success", duration_ms=result.latency_ms,
                     points_count=len(result.points))
            return result
        except Exception as e:
            log.error("AI 分析失败", module=MODULE, location=f"{self.name}.answer",
                      status="fail", error={
                          "type": type(e).__name__,
                          "message": str(e),
                          "stack": traceback.format_exc(),
                      })
            # 降级：返回可显示的兜底答案，避免 UI 卡死
            return Answer(
                question=req.question,
                opener="（AI 分析失败，以下为兜底提示）",
                points=["请自行组织回答，注意结合岗位要求与项目经历", "可先复述问题确认理解，再分点作答"],
                trace_id=req.trace_id,
                think_level=req.think_level.value,
            )
