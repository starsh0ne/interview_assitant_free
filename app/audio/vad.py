"""基于能量阈值的静音检测（VAD）切段。

纯逻辑类，不依赖音频设备，便于单元测试。
输入固定长度的 PCM chunk（16kHz/16bit/mono），累积发声段；
连续静音超过 silence_ms 则切出一段，交给下游转写。
"""
from __future__ import annotations

import numpy as np

from app.core.models import AudioSegment, Speaker


class EnergyVAD:
    def __init__(self, speaker: Speaker, sample_rate: int = 16000,
                 silence_ms: int = 800, energy_threshold: float = 0.01,
                 min_duration_ms: int = 600, max_duration_ms: int = 30000,
                 pause_after_ms: int = 400):
        self.speaker = speaker
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms
        self.energy_threshold = energy_threshold
        self.min_samples = int(sample_rate * min_duration_ms / 1000)
        self.max_samples = int(sample_rate * max_duration_ms / 1000)
        # 静音累计多久发 pause：必须显著大于词间停顿（50~200ms）、
        # 小于段尾切段（silence_ms），否则词间停顿会触发 pause 风暴
        self.pause_after_samples = int(sample_rate * pause_after_ms / 1000)
        self._buffer: list[np.ndarray] = []
        self._buf_samples = 0
        self._silence_samples = 0
        self._trace_id = ""
        self._seg_id = 0          # 当前段的 id（pause/final 共用）
        self._pause_sent = False  # 本段是否已发过 pause 事件

    def set_trace(self, trace_id: str) -> None:
        """切换新会话时更新 trace_id。"""
        self._trace_id = trace_id

    @staticmethod
    def rms(chunk: np.ndarray) -> float:
        """归一化到 0~1 的 RMS 能量。"""
        if chunk.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(chunk.astype(np.float32) / 32768.0))))

    def is_speech(self, chunk: np.ndarray) -> bool:
        return self.rms(chunk) >= self.energy_threshold

    def feed(self, chunk: np.ndarray) -> AudioSegment | None:
        """喂入一个 chunk，返回事件（pause 或切好的段），无则 None。"""
        n = chunk.size
        speech = self.is_speech(chunk)
        if speech:
            self._buffer.append(chunk)
            self._buf_samples += n
            self._silence_samples = 0
            self._pause_sent = False   # 假停顿后继续说话：允许再发 pause
        else:
            if self._buf_samples > 0:
                self._buffer.append(chunk)   # 保留静音作为词间停顿
                self._buf_samples += n
                self._silence_samples += n
            # 预转写触发：静音已累计 pause_after（400ms，明显长于词间停顿），
            # 说话大概率已结束——发 pause 快照让转写与剩余静音确认并行
            if (not self._pause_sent
                    and self._silence_samples >= self.pause_after_samples
                    and self._buf_samples >= self.min_samples):
                self._pause_sent = True
                return self._emit(is_pause=True)

        silence_limit = int(self.sample_rate * self.silence_ms / 1000)
        too_long = self._buf_samples >= self.max_samples
        if self._buf_samples >= self.min_samples and (self._silence_samples >= silence_limit or too_long):
            return self._emit()
        if too_long:
            return self._emit()   # 超长强制切段（避免一直说话不切）
        return None

    def flush(self) -> AudioSegment | None:
        """会话结束时冲刷剩余音频。"""
        if self._buf_samples >= self.min_samples:
            return self._emit()
        self._reset()
        return None

    def _emit(self, is_pause: bool = False) -> AudioSegment:
        import time
        # pause 快照只拷贝当前缓冲；final 段把缓冲消费掉
        pcm = np.concatenate(self._buffer).astype(np.int16).tobytes()
        seg = AudioSegment(
            speaker=self.speaker,
            pcm=pcm,
            trace_id=self._trace_id,
            end_ts=time.time(),
            duration_ms=int(self._buf_samples / self.sample_rate * 1000),
            seg_id=self._seg_id,
            is_pause=is_pause,
        )
        if not is_pause:
            # 快照不清空缓冲、不换段 id；final 消费时才重置
            self._reset()
            self._seg_id += 1
            self._pause_sent = False
        return seg

    def _reset(self) -> None:
        self._buffer = []
        self._buf_samples = 0
        self._silence_samples = 0
