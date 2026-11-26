"""验证窗口隐身：API 标志 + 真实抓屏对比。

用法：.venv/Scripts/python.exe tests/verify_stealth.py
"""
from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.core.config import AppConfig
from app.logging_conf import configure_logging
from app.ui.overlay import OverlayWindow
from app.ui.settings import SettingsWindow
from app.ui.stealth import get_window_stealth, set_window_stealth


def main() -> int:
    config = AppConfig.load()
    configure_logging(config.log_path)
    app = QApplication(sys.argv)

    overlay = OverlayWindow()
    settings = SettingsWindow(config)
    overlay.show()
    settings.show()
    app.processEvents()
    time.sleep(0.6)
    app.processEvents()

    failures = []
    for name, window in (("overlay", overlay), ("settings", settings)):
        hwnd = int(window.winId())
        state = get_window_stealth(hwnd)
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        tool_window = bool(ex_style & 0x80)  # WS_EX_TOOLWINDOW: 不进任务栏
        print(f"{name}: hwnd={hwnd}, stealth={state}, toolwindow={tool_window}, "
              f"label={window.stealth_label.text()}")
        if state is not True:
            failures.append(f"{name} affinity 未生效")
        if not tool_window or not (window.windowFlags() & Qt.Tool):
            failures.append(f"{name} 仍在任务栏")

    # 双击切置顶会重建原生窗口，隐身必须重新应用
    overlay.mouseDoubleClickEvent(None)
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    if get_window_stealth(int(overlay.winId())) is not True:
        failures.append("置顶切换后隐身失效")

    # 抓屏对比：隐身开时该区域不应包含悬浮窗像素；关闭后应出现
    screen = QApplication.primaryScreen()
    geo = overlay.geometry()
    shot_on = screen.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height()).toImage()

    hwnd = int(overlay.winId())
    set_window_stealth(hwnd, False)
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()
    shot_off = screen.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height()).toImage()
    set_window_stealth(hwnd, True)

    diff = 0
    for y in range(0, min(shot_on.height(), shot_off.height()), 8):
        for x in range(0, min(shot_on.width(), shot_off.width()), 8):
            if shot_on.pixel(x, y) != shot_off.pixel(x, y):
                diff += 1
    print(f"capture diff sampled pixels = {diff}")
    if diff < 50:
        failures.append("抓屏对比差异过小，隐身可能未生效")

    overlay.close()
    settings.close()
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("PASS: 两窗口 affinity 生效，抓屏对比确认隐身有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
