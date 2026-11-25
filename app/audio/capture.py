"""双源音频采集：麦克风（我方）+ WASAPI 环回（面试官）。

- 麦克风 → speaker=SELF（我方回答）
- 系统输出环回 → speaker=INTERVIEWER（面试官提问）

每个源独立线程、独立 EnergyVAD，切出的音频段放入共享队列供流水线消费。
所有线程在绑定 session trace 的上下文中运行（contextvars 需逐线程绑定）。
"""
from __future__ import annotations

import queue
import threading
import time
import traceback

import numpy as np

from app.audio.devices import AudioDevices, list_audio_devices
from app.audio.vad import EnergyVAD
from app.core.config import AppConfig
from app.core.models import AudioSegment, Speaker
from app.logging_conf import bind_session_trace, get_logger, new_trace_id, unbind_session_trace

MODULE = "audio"


class AudioCapture:
    def __init__(self, config: AppConfig, devices: AudioDevices | None = None,
                 error_callback=None):
        self.config = config
        self.devices = devices if devices is not None else list_audio_devices()
        self.segment_queue: queue.Queue[AudioSegment] = queue.Queue()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._trace_id = ""
        self._error_callback = error_callback  # (speaker: str, message: str) -> None
        self._log = get_logger()

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def start(self) -> None:
        """启动双源采集。trace_id 在会话开始时生成，全链路共用。"""
        if self._threads:
            return
        self._stop_event.clear()
        self._trace_id = new_trace_id()
        self._log.info("音频采集启动", module=MODULE, location="AudioCapture.start",
                       status="start", sample_rate=self.config.sample_rate,
                       mic_devices=len(self.devices.mics), speaker_devices=len(self.devices.speakers))

        mic_device = self.devices.get_mic(None)
        speaker_device = self.devices.get_speaker(None)

        if mic_device is None and speaker_device is None:
            self._log.error("未找到任何音频设备", module=MODULE, location="AudioCapture.start",
                            status="fail", error={"type": "NoAudioDeviceError",
                                                  "message": "系统无可用麦克风或扬声器", "stack": ""})
            return

        if mic_device is not None:
            t = threading.Thread(target=self._capture_loop,
                                 args=(mic_device, Speaker.SELF),
                                 name="cap-mic", daemon=True)
            self._threads.append(t)
        if speaker_device is not None:
            t = threading.Thread(target=self._capture_loop,
                                 args=(speaker_device, Speaker.INTERVIEWER),
                                 name="cap-loopback", daemon=True)
            self._threads.append(t)

        for t in self._threads:
            t.start()

    def _capture_loop(self, device, speaker: Speaker) -> None:
        """单个源的采集循环。"""
        bind_session_trace(self._trace_id, location=f"AudioCapture.{speaker.value}")
        log = get_logger()
        sr = self.config.sample_rate
        chunk_frames = int(sr * 0.02)   # 20ms/chunk
        vad = EnergyVAD(
            speaker=speaker,
            sample_rate=sr,
            silence_ms=self.config.vad_silence_ms,
            energy_threshold=self.config.vad_energy_threshold,
        )
        vad.set_trace(self._trace_id)

        try:
            # devices.py 已保证：mic 与环回源都是可 record 的 _Microphone 对象
            source = device
            source_name = getattr(device, "name", "<unnamed>")

            log.info("采集线程就绪", module=MODULE, location="AudioCapture._capture_loop",
                     status="start", speaker=speaker.value, device=source_name,
                     samplerate=sr, channels=1)

            # soundcard 在缓冲区被抢（会议软件/系统音频引擎调度）时会发
            # SoundcardRuntimeWarning: data discontinuity —— 该 chunk 数据残缺，
            # 直接喂 VAD 会误判成静音导致提前切段。本地计数并静默丢弃警告刷屏。
            import warnings
            from soundcard import SoundcardRuntimeWarning
            discontinuity = 0

            while not self._stop_event.is_set():
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", SoundcardRuntimeWarning)
                    # record 返回 float32 [-1,1]，shape=(frames, channels)
                    data = source.record(numframes=chunk_frames, samplerate=sr, channels=1)
                if any(issubclass(w.category, SoundcardRuntimeWarning) for w in caught):
                    discontinuity += 1
                    # 这句是残缺数据，跳过不喂 VAD（避免提前切段）
                    continue
                arr = np.asarray(data)
                mono = arr.reshape(-1)
                if mono.size == 0:
                    continue
                # 必须缩放后再转 int16：直接 astype 会把 [-1,1] 全压成 0，VAD 永远不触发
                if np.issubdtype(arr.dtype, np.floating):
                    mono = (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)
                else:
                    mono = mono.astype(np.int16)
                seg = vad.feed(mono)
                if seg is not None:
                    self.segment_queue.put(seg)
                    log.info("VAD 切段完成", module=MODULE, location="AudioCapture._capture_loop",
                             status="success", speaker=speaker.value,
                             duration_ms=seg.duration_ms, trace_id=seg.trace_id,
                             discontinuity=discontinuity)
                    discontinuity = 0
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            log.error("采集线程异常", module=MODULE, location="AudioCapture._capture_loop",
                      status="fail", speaker=speaker.value,
                      error={"type": type(e).__name__, "message": str(e),
                             "stack": traceback.format_exc()})
            # 立即通知 UI：否则悬浮窗停在"辅助中"，用户以为正常实则已死
            if self._error_callback is not None:
                try:
                    self._error_callback(speaker.value, detail)
                except Exception as cb_err:
                    log.error("采集异常回调失败", module=MODULE,
                              location="AudioCapture._capture_loop", status="fail",
                              error={"type": type(cb_err).__name__, "message": str(cb_err), "stack": ""})
        finally:
            seg = vad.flush()
            if seg is not None:
                self.segment_queue.put(seg)
            unbind_session_trace()

    def stop(self) -> None:
        """停止采集，冲刷所有 VAD 缓冲。"""
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads = []
        self._log.info("音频采集停止", module=MODULE, location="AudioCapture.stop",
                       status="success", trace_id=self._trace_id)
