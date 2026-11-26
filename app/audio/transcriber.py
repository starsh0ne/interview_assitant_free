"""本地异步语音转写（faster-whisper）。

- 模型懒加载：首次转写时才加载，避免启动卡顿。
- 线程池执行：不阻塞 UI 线程与音频采集线程。
- 每个任务在线程池中重新绑定 trace_id（contextvars 不跨线程继承）。
"""
from __future__ import annotations

import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from app.core.config import AppConfig
from app.core.models import AudioSegment, Speaker, Transcript
from app.logging_conf import bind_session_trace, get_logger, unbind_session_trace

MODULE = "transcriber"


class Transcriber:
    def __init__(self, config: AppConfig):
        self.config = config
        self._model = None
        self._hotwords: str = ""   # 领域词提示，由 pipeline.start 注入
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
        self._log = get_logger()

    def set_hotwords(self, hotwords: str) -> None:
        """设置 Whisper 领域词提示（空串=不注入）。线程安全：仅在 start 前调用。"""
        self._hotwords = (hotwords or "").strip()
        self._log.info("领域词提示已设置", module=MODULE, location="Transcriber.set_hotwords",
                       status="success", word_count=len(self._hotwords.split()) if self._hotwords else 0)

    def _get_model(self):
        if self._model is None:
            import os
            from pathlib import Path
            from faster_whisper import WhisperModel

            # 模型已预下载到本地时强制离线加载：避免 huggingface_hub 联网校验
            # 在代理不通的环境报 502（模型文件本身就在本地，无需联网）。
            hf_home = Path(os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface")))
            if (hf_home / "hub").exists():
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                offline = True
            else:
                offline = False

            self._log.info("加载转写模型", module=MODULE, location="Transcriber._get_model",
                           status="start", model=self.config.whisper_model,
                           device=self.config.whisper_device, offline=offline)
            start = time.perf_counter()
            self._model = WhisperModel(
                self.config.whisper_model,
                device=self.config.whisper_device,
                compute_type=self.config.whisper_compute_type,
            )
            self._log.info("转写模型加载完成", module=MODULE, location="Transcriber._get_model",
                           status="success", duration_ms=int((time.perf_counter()-start)*1000))
        return self._model

    @staticmethod
    def _filter_hallucination(text: str) -> str:
        """过滤 whisper 在静音/弱信号上产生的固定幻觉字幕（非真实语音）。"""
        if not text:
            return ""
        hallucinations = ("字幕由", "字幕by", "字幕 BY", "请不吝点赞", "订阅", "转发", "MUSIC", "谢谢观看")
        cleaned = text.strip()
        for phrase in hallucinations:
            if cleaned == phrase or cleaned.startswith(phrase):
                return ""
        return cleaned

    def submit(self, segment: AudioSegment) -> Future[Transcript]:
        """提交转写任务，立即返回 Future。"""
        return self._executor.submit(self._transcribe, segment)

    def _transcribe(self, segment: AudioSegment) -> Transcript:
        bind_session_trace(segment.trace_id, location="Transcriber._transcribe")
        log = get_logger()
        start = time.perf_counter()
        log.info("转写开始", module=MODULE, location="Transcriber._transcribe",
                 status="start", speaker=segment.speaker.value, duration_ms=segment.duration_ms,
                 hotwords_count=len(self._hotwords.split()) if self._hotwords else 0)
        try:
            audio = np.frombuffer(segment.pcm, dtype=np.int16).astype(np.float32) / 32768.0
            model = self._get_model()
            decode_kwargs = dict(
                language="zh",
                beam_size=1,   # 贪心解码：CPU 上比 beam=5 快 2-3 倍，中文短句准确率损失可忽略
                vad_filter=True,
            )
            if self._hotwords:
                decode_kwargs["hotwords"] = self._hotwords
            segments, _info = model.transcribe(audio, **decode_kwargs)
            text = "".join(s.text for s in segments).strip()
            text = self._filter_hallucination(text)

            # 容错：环回偶发 data discontinuity 会截出半句/静音段，
            # whisper 内置 VAD 会把它们全过滤成空文本——关掉 VAD 再试一次。
            retried = False
            if not text:
                retried = True
                log.warning("转写为空，关闭 VAD 重试", module=MODULE,
                            location="Transcriber._transcribe", status="retry",
                            speaker=segment.speaker.value, duration_ms=segment.duration_ms)
                retry_kwargs = dict(language="zh", beam_size=1, vad_filter=False)
                if self._hotwords:
                    retry_kwargs["hotwords"] = self._hotwords
                segments, _info = model.transcribe(audio, **retry_kwargs)
                text = "".join(s.text for s in segments).strip()
                text = self._filter_hallucination(text)

            latency = int((time.perf_counter() - start) * 1000)
            log.info("转写完成", module=MODULE, location="Transcriber._transcribe",
                     status="success", speaker=segment.speaker.value,
                     latency_ms=latency, text_len=len(text), retried=retried,
                     text=text)   # 原文入日志：误转/错命中可直接回溯（logs/ 已 gitignore）
            return Transcript(text=text, speaker=segment.speaker,
                              trace_id=segment.trace_id, duration_ms=segment.duration_ms,
                              latency_ms=latency)
        except Exception as e:
            log.error("转写失败", module=MODULE, location="Transcriber._transcribe",
                      status="fail", speaker=segment.speaker.value,
                      error={"type": type(e).__name__, "message": str(e),
                             "stack": traceback.format_exc()})
            return Transcript(text="", speaker=segment.speaker,
                              trace_id=segment.trace_id, duration_ms=segment.duration_ms,
                              latency_ms=int((time.perf_counter()-start)*1000))
        finally:
            unbind_session_trace()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
