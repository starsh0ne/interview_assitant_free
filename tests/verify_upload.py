"""回归验证：上传简历后应用不得退出，速查卡应正常生成。

背景：两个窗口都是 Qt.Tool，Qt 默认 quitOnLastWindowClosed=True 时，
上传简历弹出的原生文件对话框关闭后会被误判为"最后一个主窗口已关闭"，
导致整个进程退出（界面消失、日志停在"简历上传成功"）。

运行：
    .venv/Scripts/python.exe tests/verify_upload.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from app.core.config import AppConfig
import app.ui.settings as settings_mod
from app.ui.overlay import OverlayWindow
from app.ui.settings import SettingsWindow

FAKE_RESUME = (
    "姓名：测试候选人\n求职方向：后端开发\n工作年限：5 年\n"
    "项目经历：主导高并发系统改造，QPS 从 1000 提升至 5000。\n"
    "最高学历：硕士\n"
) * 40
FAKE_PATH = str(PROJECT_ROOT / "tests" / "fake_resume.pdf")


def main() -> int:
    # 用假文本替换解析，聚焦"上传后是否退出"这条路径
    settings_mod.parse_resume = lambda path: FAKE_RESUME
    settings_mod.supported_extensions = lambda: [".pdf", ".docx"]

    config = AppConfig.load()
    app = QApplication(sys.argv)
    # 与 main.py 一致的关键设置
    app.setQuitOnLastWindowClosed(False)

    overlay = OverlayWindow()
    settings = SettingsWindow(config)
    overlay.show()
    settings.show()

    # 模拟用户在原生文件对话框里选了简历
    QFileDialog.getOpenFileName = lambda *a, **k: (FAKE_PATH, "")

    state = {"uploaded": False, "alive_at_5s": False, "card_ready": False}

    def do_upload():
        settings._pick_resume()
        state["uploaded"] = bool(settings.resume_text)

    def check_alive():
        # 关键断言：5 秒后事件循环仍在跑（旧行为此时进程已退出，本回调不会执行）
        state["alive_at_5s"] = QApplication.instance() is not None
        state["card_ready"] = bool(settings.resume_card.strip())
        app.quit()

    QTimer.singleShot(200, do_upload)
    QTimer.singleShot(5000, check_alive)

    app.exec()

    print(f"uploaded={state['uploaded']}")
    print(f"alive_at_5s={state['alive_at_5s']}")
    print(f"card_ready={state['card_ready']} card_len={len(settings.resume_card)}")

    ok = state["uploaded"] and state["alive_at_5s"] and state["card_ready"]
    print("PASS: 上传简历后应用存活，速查卡正常生成" if ok else "FAIL: 上传后行为异常")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
