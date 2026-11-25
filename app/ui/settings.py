"""设置面板：上传简历、选择思考强度/设备、配置 API Key、开始/停止采集。

API Key 只存在内存中，不落盘；如环境变量已配置则预填（脱敏显示）。
简历上传后后台生成 AI「速查卡」（一次压缩成 ~300 字），此后每次提问只携带
速查卡而非简历全文：prompt 更短（生成更快）且回答更聚焦核心背景。
"""
from __future__ import annotations

import os
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.audio.devices import list_audio_devices
from app.core.config import AppConfig
from app.core.models import ThinkLevel
from app.logging_conf import get_logger
from app.resume.parser import parse_resume, supported_extensions
from app.ui.stealth import STEALTH_LABEL, apply_stealth_to_widget

MODULE = "settings"

RESUME_CARD_PROMPT = """把下面的简历压缩成一张「面试速查卡」，供面试实时辅助使用。

要求（只输出速查卡正文，不要任何解释或标题）：
- 300 字以内
- 包含：姓名 / 求职方向 / 工作年限 / 核心技术栈 / 最亮的 2-3 个项目成果（必须保留具体数字，如 QPS、规模、百分比）/ 最高学历
- 用紧凑的事实罗列，不用完整句子也行
- 删掉与面试答题无关的信息（自我评价套话、兴趣爱好等）"""


class SettingsWindow(QWidget):
    start_requested = Signal()   # 用户点"开始"
    stop_requested = Signal()    # 用户点"停止"
    # 速查卡生成完成（后台线程 → UI 需跨线程，用信号）
    resume_card_ready = Signal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.resume_text = ""
        self.resume_card = ""     # AI 速查卡；为空时降级用简历前 600 字
        self._card_gen_lock = threading.Lock()
        self._devices = list_audio_devices()
        self._log = get_logger()
        self.setWindowTitle("面试辅助 · 设置")
        self.setMinimumWidth(520)
        self._build_ui()
        self.resume_card_ready.connect(self._on_card_ready)

    @property
    def effective_resume(self) -> str:
        """提问时实际携带的上下文：速查卡优先，未就绪降级为简历前 600 字。"""
        if self.resume_card.strip():
            return self.resume_card
        return self.resume_text[:600]

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self.stealth_label = QLabel(STEALTH_LABEL)
        self.stealth_label.setStyleSheet("color: #1f8a4c; font-weight: bold;")
        self.stealth_label.setWordWrap(True)
        root.addWidget(self.stealth_label)

        # 简历
        resume_box = QGroupBox("1. 上传简历（开始前必填）")
        rl = QHBoxLayout(resume_box)
        self.resume_path = QLineEdit()
        self.resume_path.setReadOnly(True)
        self.resume_path.setPlaceholderText("PDF / DOCX")
        btn_pick = QPushButton("选择文件...")
        btn_pick.clicked.connect(self._pick_resume)
        rl.addWidget(self.resume_path, 1)
        rl.addWidget(btn_pick)
        self.resume_status = QLabel("未上传")
        root.addWidget(resume_box)
        root.addWidget(self.resume_status)

        # 思考强度
        think_box = QGroupBox("2. AI 思考强度")
        tl = QHBoxLayout(think_box)
        self.think_combo = QComboBox()
        self.think_combo.addItem("低（快速要点，默认）", ThinkLevel.LOW.value)
        self.think_combo.addItem("中（标准分析）", ThinkLevel.MEDIUM.value)
        self.think_combo.addItem("高（深度分析）", ThinkLevel.HIGH.value)
        self.think_combo.setCurrentIndex(0)
        tl.addWidget(self.think_combo)
        root.addWidget(think_box)

        # 设备
        dev_box = QGroupBox("3. 音频设备")
        fl = QFormLayout(dev_box)
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("默认麦克风", "")
        for d in self._devices.mics:
            self.mic_combo.addItem(d.label, d.name)
        self.spk_combo = QComboBox()
        self.spk_combo.addItem("默认系统输出（WASAPI 环回）", "")
        for d in self._devices.speakers:
            self.spk_combo.addItem(d.label, d.name)
        fl.addRow("麦克风（我方）:", self.mic_combo)
        fl.addRow("系统输出（面试官）:", self.spk_combo)
        root.addWidget(dev_box)

        # API Key
        key_box = QGroupBox("4. DeepSeek API Key")
        kl = QVBoxLayout(key_box)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        env_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if env_key:
            self.key_input.setText(env_key)
        kl.addWidget(self.key_input)
        kl.addWidget(QLabel("从环境变量 DEEPSEEK_API_KEY 预填；留空则使用配置文件中的值。密钥不写入磁盘。"))
        root.addWidget(key_box)

        # 按钮
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("开始辅助")
        self.btn_start.setStyleSheet("background:#2d7d46; color:white; padding:8px;")
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        root.addLayout(btn_row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_stealth_to_widget(self, self.stealth_label)

    def _pick_resume(self) -> None:
        exts = " ".join(f"*{e}" for e in supported_extensions())
        path, _ = QFileDialog.getOpenFileName(
            self, "选择简历文件", "", f"简历文件 ({exts});;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            text = parse_resume(path)
            self.resume_text = text
            self.resume_card = ""   # 新简历：作废旧速查卡
            self.resume_path.setText(path)
            self.resume_status.setText(f"已加载 · {len(text)} 字符 · 速查卡生成中...")
            self.resume_status.setStyleSheet("color:#b8860b;")
            self._log.info("简历上传成功", module=MODULE, location="SettingsWindow._pick_resume",
                           status="success", file_ext=Path(path).suffix, text_len=len(text))
            self._generate_card_async(text)
        except ValueError as e:
            QMessageBox.warning(self, "简历解析失败", str(e))
            self._log.error("简历上传失败", module=MODULE, location="SettingsWindow._pick_resume",
                            status="fail", error={"type": "ValueError", "message": str(e), "stack": ""})

    def _generate_card_async(self, text: str) -> None:
        """后台线程生成速查卡（3-6s）；期间用户仍可直接开始（走降级文本）。"""
        if not self.config.deepseek_api_key:
            # Key 未配（面板稍后可能输入）：先降级，_on_start 时若已填可再生成
            self.resume_status.setText(f"已加载 · {len(text)} 字符（未配 Key，速查卡跳过）")
            self.resume_status.setStyleSheet("color:#2d7d46;")
            return

        def worker():
            if not self._card_gen_lock.acquire(blocking=False):
                return  # 已有生成任务在跑
            try:
                from app.llm.deepseek import DeepSeekLLM
                from openai import OpenAI
                client = DeepSeekLLM(self.config)
                resp = client.client.chat.completions.create(
                    model=self.config.deepseek_model,
                    messages=[
                        {"role": "system", "content": RESUME_CARD_PROMPT},
                        {"role": "user", "content": text[:6000]},
                    ],
                    max_tokens=500,
                    stream=False,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                card = (resp.choices[0].message.content or "").strip()
                self.resume_card_ready.emit(card if card else "")
            except Exception as e:
                self._log.error("速查卡生成失败", module=MODULE,
                                location="SettingsWindow._generate_card_async", status="fail",
                                error={"type": type(e).__name__, "message": str(e),
                                       "stack": traceback.format_exc()})
                self.resume_card_ready.emit("")
            finally:
                self._card_gen_lock.release()

        threading.Thread(target=worker, name="card-gen", daemon=True).start()

    def _on_card_ready(self, card: str) -> None:
        """速查卡结果回到 UI 线程更新状态。"""
        if card.strip():
            self.resume_card = card
            self.resume_status.setText(f"速查卡就绪 · {len(card)} 字（提问将使用）")
            self.resume_status.setStyleSheet("color:#2d7d46;")
            self._log.info("速查卡生成完成", module=MODULE,
                           location="SettingsWindow._on_card_ready", status="success",
                           card_len=len(card))
        else:
            self.resume_status.setText(f"已加载 · 速查卡生成失败，将使用简历前 600 字")
            self.resume_status.setStyleSheet("color:#2d7d46;")

    def _on_start(self) -> None:
        if not self.resume_text:
            QMessageBox.information(self, "请先上传简历", "开始前必须上传 PDF / DOCX 简历。")
            return
        # 用户输入的 key 覆盖配置（仅内存）
        key = self.key_input.text().strip()
        if key:
            self.config.deepseek_api_key = key
        if not self.config.deepseek_api_key:
            QMessageBox.warning(self, "缺少 API Key", "请填写 DeepSeek API Key 或设置 DEEPSEEK_API_KEY 环境变量。")
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._log.info("用户点击开始", module=MODULE, location="SettingsWindow._on_start",
                       status="success", think_level=self.think_combo.currentData(),
                       mic=self.mic_combo.currentData() or "default",
                       speaker=self.spk_combo.currentData() or "default")
        self.start_requested.emit()

    def on_stopped(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
