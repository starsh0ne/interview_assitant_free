"""interview-assist 主入口。

启动流程：
1. 配置日志
2. 创建 Qt 应用、悬浮窗、设置面板
3. 用户上传简历并点击开始 → 创建采集器/转写器/LLM/流水线 → 启动
4. 用户点停止 → 停止流水线与采集
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 支持 `python app/main.py` 直接启动：把项目根加入模块搜索路径
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.audio.capture import AudioCapture
from app.audio.devices import list_audio_devices
from app.audio.transcriber import Transcriber
from app.core.config import AppConfig
from app.core.models import ThinkLevel
from app.llm.deepseek import DeepSeekLLM
from app.logging_conf import configure_logging, get_logger
from app.pipeline import Pipeline
from app.ui.overlay import OverlayWindow
from app.ui.settings import SettingsWindow

MODULE = "main"


def main() -> int:
    config = AppConfig.load()
    configure_logging(config.log_path)
    log = get_logger()
    log.info("应用启动", module=MODULE, location="main", status="start",
             model=config.deepseek_model, think_level=config.think_level.value,
             api_key_configured=bool(config.deepseek_api_key))

    app = QApplication(sys.argv)
    overlay = OverlayWindow()
    settings = SettingsWindow(config)
    overlay.show()
    settings.show()

    pipeline: Pipeline | None = None
    capture: AudioCapture | None = None
    err_timer: QTimer | None = None

    def on_start():
        nonlocal pipeline, capture, err_timer
        try:
            if err_timer is not None:
                err_timer.stop()
                err_timer = None
            overlay.title.setText("启动中...")
            # 按用户选择设置设备
            devices = list_audio_devices()
            mic_name = settings.mic_combo.currentData()
            spk_name = settings.spk_combo.currentData()
            # 用选中的设备重建 devices 顺序（get_mic/get_spk 按 name 精确匹配）
            from app.audio.devices import DeviceInfo
            if mic_name:
                for i, d in enumerate(devices.mics):
                    if d.name == mic_name:
                        devices.mics.insert(0, devices.mics.pop(i))
                        break
            if spk_name:
                for i, d in enumerate(devices.speakers):
                    if d.name == spk_name:
                        devices.speakers.insert(0, devices.speakers.pop(i))
                        break

            level = ThinkLevel(settings.think_combo.currentData())
            llm = DeepSeekLLM(config)
            transcriber = Transcriber(config)

            # 采集线程异常时跨线程推 UI：用队列 + QTimer 轮询（QObject 信号需主线程 emit）
            capture_errors: list[tuple[str, str]] = []

            def on_capture_error(speaker: str, message: str):
                capture_errors.append((speaker, message))
                log.error("采集异常上报 UI", module=MODULE, location="main.on_capture_error",
                          status="fail", speaker=speaker, message=message)

            def drain_capture_errors():
                while capture_errors:
                    speaker, message = capture_errors.pop(0)
                    who = "面试官" if speaker == "interviewer" else "麦克风"
                    overlay.on_error("audio", f"{who}采集失败：{message}", "-")
                    settings.on_stopped()

            err_timer = QTimer()
            err_timer.timeout.connect(drain_capture_errors)
            err_timer.start(300)

            capture = AudioCapture(config, devices=devices, error_callback=on_capture_error)

            pipeline = Pipeline(config, capture, transcriber, llm)
            pipeline.transcript_ready.connect(overlay.on_transcript)
            pipeline.answer_line_ready.connect(overlay.on_answer_line)
            pipeline.answer_ready.connect(overlay.on_answer)
            pipeline.status_changed.connect(overlay.on_status)
            pipeline.error_occurred.connect(overlay.on_error)

            # 先启动流水线（工作线程就绪），再启动采集；用速查卡（降级为简历前600字）
            pipeline.start(settings.effective_resume, level)
            capture.start()

            # D-预热：后台预载 whisper 模型 + LLM 建连，消除首次真实调用的冷启动
            import threading

            def _warmup():
                try:
                    llm.warmup()
                    transcriber._get_model()
                except Exception:
                    pass  # 预热失败不影响主流程，首次调用时会再加载

            threading.Thread(target=_warmup, name="warmup", daemon=True).start()

            overlay.on_status("辅助中 · 面试官提问或对镜说话即触发")
            log.info("辅助会话已启动", module=MODULE, location="main.on_start", status="success",
                     capture_threads=len(capture._threads) if capture else 0)
        except Exception as e:
            log.error("启动失败", module=MODULE, location="main.on_start",
                      status="fail", error={"type": type(e).__name__, "message": str(e),
                                            "stack": traceback.format_exc()})
            overlay.on_error(MODULE, f"启动失败: {e}", "-")
            settings.on_stopped()

    def on_stop():
        nonlocal pipeline, capture, err_timer
        try:
            if err_timer is not None:
                err_timer.stop()
                err_timer = None
            if capture:
                capture.stop()
                capture = None
            if pipeline:
                pipeline.stop()
                pipeline = None
            overlay.on_status("已停止 · 可在设置面板重新开始")
            settings.on_stopped()
            log.info("辅助会话已停止", module=MODULE, location="main.on_stop", status="success")
        except Exception as e:
            log.error("停止异常", module=MODULE, location="main.on_stop",
                      status="fail", error={"type": type(e).__name__, "message": str(e),
                                            "stack": traceback.format_exc()})

    settings.start_requested.connect(on_start)
    settings.stop_requested.connect(on_stop)

    log.info("应用初始化完成", module=MODULE, location="main", status="success")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
