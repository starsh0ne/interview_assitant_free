"""Windows 窗口隐身：阻止窗口进入截屏 / 录屏 / 会议共享，本地仍可见可交互。

底层是 Win32 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)。
注意：这是窗口级排除，不能只对某一个软件隐身；失败时只记日志并降级，不影响主流程。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from app.logging_conf import get_logger

MODULE = "stealth"

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011

STEALTH_LABEL = "● 隐身中 · 仅本地可见"
STEALTH_FAIL_LABEL = "⚠ 隐身不可用 · 共享时对方可见"
STEALTH_OK_STYLE = "color: #6fdc9a;"
STEALTH_FAIL_STYLE = "color: #ffb86b;"

_user32 = None


def _get_user32():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
        u.SetWindowDisplayAffinity.restype = wintypes.BOOL
        u.GetWindowDisplayAffinity.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        u.GetWindowDisplayAffinity.restype = wintypes.BOOL
        _user32 = u
    return _user32


def set_window_stealth(hwnd: int, enabled: bool = True) -> bool:
    """设置 / 取消窗口隐身，返回是否成功。"""
    log = get_logger()
    if sys.platform != "win32" or not hwnd:
        log.warning("隐身不可用：非 Windows 或无窗口句柄", module=MODULE,
                    location="set_window_stealth", status="fail", hwnd=hwnd)
        return False
    try:
        value = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        ok = bool(_get_user32().SetWindowDisplayAffinity(
            wintypes.HWND(hwnd), wintypes.DWORD(value)))
        if not ok:
            err = ctypes.get_last_error()
            log.warning("设置窗口隐身失败", module=MODULE, location="set_window_stealth",
                        status="fail", hwnd=hwnd, win32_error=err)
            return False
        log.info("窗口隐身已设置", module=MODULE, location="set_window_stealth",
                 status="success", hwnd=hwnd, enabled=enabled)
        return True
    except Exception as exc:
        log.warning("设置窗口隐身异常", module=MODULE, location="set_window_stealth",
                    status="fail", hwnd=hwnd, error=f"{type(exc).__name__}: {exc}")
        return False


def get_window_stealth(hwnd: int) -> bool | None:
    """读取窗口当前隐身状态；读取失败返回 None。"""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        value = wintypes.DWORD(0)
        ok = _get_user32().GetWindowDisplayAffinity(
            wintypes.HWND(hwnd), ctypes.byref(value))
        return bool(ok and value.value == WDA_EXCLUDEFROMCAPTURE)
    except Exception:
        return None


def apply_stealth_to_widget(widget, label=None) -> bool:
    """对 Qt 顶层窗口应用隐身，可选同步更新状态标签。"""
    hwnd = int(widget.winId())
    ok = set_window_stealth(hwnd, True)
    if label is not None:
        label.setText(STEALTH_LABEL if ok else STEALTH_FAIL_LABEL)
        label.setStyleSheet(STEALTH_OK_STYLE if ok else STEALTH_FAIL_STYLE)
    return ok
