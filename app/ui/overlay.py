"""半透明置顶悬浮窗：显示问题与要点式答案。

- FramelessWindowHint + WindowStaysOnTopHint + 半透明
- 鼠标拖动移动窗口，双击切换置顶/取消置顶
- 只显示文本，不抢焦点（WindowDoesNotAcceptFocus）
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.logging_conf import get_logger
from app.ui.stealth import STEALTH_LABEL, apply_stealth_to_widget

MODULE = "ui"


class OverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.88)
        self.setGeometry(100, 100, 620, 460)
        self._drag_pos = None
        self._pinned = True
        self._stream_lines = 0
        self._log = get_logger()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame()
        self.card.setObjectName("overlayCard")
        self.card.setStyleSheet("""
            QFrame#overlayCard {
                background: rgba(18, 20, 26, 230);
                border: 1px solid rgba(120, 160, 220, 120);
                border-radius: 12px;
            }
            QLabel { color: #e8eaf0; }
        """)
        inner = QVBoxLayout(self.card)
        inner.setContentsMargins(18, 14, 18, 14)
        inner.setSpacing(10)

        self.title = QLabel("面试辅助 · 等待开始")
        self.title.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.title.setStyleSheet("color: #7fb0ff;")
        inner.addWidget(self.title)

        self.q_label = QLabel("面试官问题将显示在这里")
        self.q_label.setWordWrap(True)
        self.q_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        inner.addWidget(self.q_label)

        self.a_label = QLabel("AI 回答要点将显示在这里")
        self.a_label.setWordWrap(True)
        self.a_label.setFont(QFont("Microsoft YaHei", 11))
        self.a_label.setStyleSheet("color: #c8d4e8; line-height: 150%;")
        inner.addWidget(self.a_label)

        self.hint = QLabel("拖动移动 · 双击切换置顶 · 关闭请到设置面板")
        self.hint.setFont(QFont("Microsoft YaHei", 9))
        self.hint.setStyleSheet("color: #7a8296;")
        inner.addWidget(self.hint)

        self.stealth_label = QLabel(STEALTH_LABEL)
        self.stealth_label.setFont(QFont("Microsoft YaHei", 9))
        self.stealth_label.setStyleSheet("color: #6fdc9a;")
        inner.addWidget(self.stealth_label)

        outer.addWidget(self.card)

    def showEvent(self, event) -> None:
        """原生窗口创建后应用隐身；双击切置顶重建窗口时也会再次触发。"""
        super().showEvent(event)
        apply_stealth_to_widget(self, self.stealth_label)

    # ---- 拖动 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        self._pinned = not self._pinned
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if self._pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        apply_stealth_to_widget(self, self.stealth_label)
        self._log.info("置顶状态切换", module=MODULE, location="OverlayWindow.mouseDoubleClickEvent",
                       status="success", pinned=self._pinned)

    # ---- 显示更新（由 Qt 信号触发，运行在 UI 线程）----
    @Slot(str, str, str)
    def on_transcript(self, speaker: str, text: str, trace_id: str) -> None:
        who = "面试官" if speaker == "interviewer" else "我方"
        self.title.setText(f"识别到{who}发言 · {trace_id[:8]}")
        # 把识别文本真正显示出来；空文本也要明确提示，避免用户以为卡住
        if text and text != "（未识别到语音）":
            self.q_label.setText(f"{who}: {text}")
        else:
            self.q_label.setText(f"{who}: （未识别到语音，请靠近麦克风/调大音量重试）")
        self._log.info("悬浮窗显示转写", module=MODULE, location="OverlayWindow.on_transcript",
                       status="success", speaker=speaker, text_len=len(text))

    @Slot(str, str, str)
    def on_answer_line(self, kind: str, text: str, trace_id: str) -> None:
        """流式逐行显示：首行结论立刻上屏，要点逐条追加。"""
        if kind == "opener":
            self.title.setText(f"AI 回答中 · {trace_id[:8]}")
            self.a_label.setText(f"➤ {text}")
            self._stream_lines = 1
        else:
            current = self.a_label.text() if self._stream_lines else ""
            self.a_label.setText(f"{current}\n• {text}" if current else f"• {text}")
            self._stream_lines = self._stream_lines + 1
        self._log.info("悬浮窗流式行", module=MODULE, location="OverlayWindow.on_answer_line",
                       status="success", kind=kind, text_len=len(text))

    @Slot(str, str, list, str)
    def on_answer(self, question: str, opener: str, points: list, trace_id: str) -> None:
        self.title.setText(f"AI 回答 · {trace_id[:8]}")
        self._stream_lines = 0   # 流式结束，最终幂等重绘
        self.q_label.setText(f"Q: {question}")
        lines = []
        if opener:
            lines.append(opener)
        lines.extend(f"{i}. {p}" for i, p in enumerate(points, 1))
        self.a_label.setText("\n".join(lines))
        self._log.info("悬浮窗显示答案", module=MODULE, location="OverlayWindow.on_answer",
                       status="success", points_count=len(points), trace_id=trace_id)

    @Slot(str)
    def on_status(self, text: str) -> None:
        self.title.setText(text)

    @Slot(str, str, str)
    def on_error(self, module: str, message: str, trace_id: str) -> None:
        self.title.setText(f"错误({module}) · {trace_id[:8]}")
        self.a_label.setText(message)
