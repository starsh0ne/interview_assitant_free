"""跨模块传递的数据结构。每个对象带 trace_id，保证全链路可追溯。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class Speaker(str, Enum):
    """说话人来源。线上面试：loopback=面试官，mic=我方。"""
    INTERVIEWER = "interviewer"   # 系统输出环回 → 面试官提问
    SELF = "self"                 # 麦克风 → 我方回答


class ThinkLevel(str, Enum):
    """AI 思考强度三档，默认 low。"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AudioSegment:
    """VAD 切出的一段音频。

    is_pause=True 表示"说话刚停"的暂停事件（预转写用）：音频是暂停时刻的
    缓冲快照，转写结果待最终段确认后复用，省去串行等待。
    """
    speaker: Speaker
    pcm: bytes                    # 16kHz / 16bit / mono
    trace_id: str
    start_ts: float = field(default_factory=time.time)
    end_ts: float = 0.0
    duration_ms: int = 0
    seg_id: int = 0               # 同一段语音的 pause 与 final 共用 id
    is_pause: bool = False

    @staticmethod
    def new_trace_id() -> str:
        return uuid.uuid4().hex[:12]


@dataclass
class Transcript:
    """转写结果。"""
    text: str
    speaker: Speaker
    trace_id: str
    duration_ms: int = 0
    latency_ms: int = 0


@dataclass
class Answer:
    """AI 分析后的要点式回答。"""
    question: str
    points: list[str]             # 3-5 条要点
    opener: str = ""              # 简短开场
    trace_id: str = ""
    latency_ms: int = 0
    think_level: str = "low"
