"""应用配置：环境变量 + 本地 JSON 配置。

环境变量优先级高于 JSON。敏感信息（API Key）只从环境变量读取，不落盘。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.models import ThinkLevel

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.local.json"

# Whisper 模型缓存固定到项目内 .models（避免污染用户目录，且启动脚本与直接运行一致）
# 仅在用户未显式设置 HF_HOME 时生效
if not os.environ.get("HF_HOME"):
    os.environ["HF_HOME"] = str(PROJECT_ROOT / ".models")


class AppConfig(BaseModel):
    # DeepSeek（OpenAI 兼容）
    deepseek_api_key: str = Field(default="", description="从 DEEPSEEK_API_KEY 环境变量读取")
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    # deepseek-flash = DeepSeek-V4.1-Flash（官方模型列表实测有效）
    deepseek_model: str = "deepseek-flash"

    # 思考强度映射：低=快速要点，中=标准，高=深度分析
    think_level: ThinkLevel = ThinkLevel.LOW

    # 音频采集
    sample_rate: int = 16000          # faster-whisper 目标采样率
    mic_device_index: int | None = None   # None=默认麦克风
    loopback_device_index: int | None = None  # None=默认系统输出环回
    vad_silence_ms: int = 800         # 静音多久切一段（实测 1500 太慢；800ms 面试停顿即切段）
    vad_energy_threshold: float = 0.01  # RMS 能量阈值（0~1）

    # 转写
    whisper_model: str = "small"      # tiny/base/small/medium/large-v3
    whisper_device: str = "cpu"       # cpu / cuda
    whisper_compute_type: str = "int8"

    # 日志
    log_path: str = str(PROJECT_ROOT / "logs" / "app.jsonl")

    @classmethod
    def load(cls) -> "AppConfig":
        data: dict = {}
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        # 环境变量覆盖（只覆盖已知字段）
        env_map = {
            "DEEPSEEK_API_KEY": "deepseek_api_key",
            "DEEPSEEK_BASE_URL": "deepseek_base_url",
            "DEEPSEEK_MODEL": "deepseek_model",
            "THINK_LEVEL": "think_level",
            "WHISPER_MODEL": "whisper_model",
            "WHISPER_DEVICE": "whisper_device",
        }
        for env_key, field in env_map.items():
            if os.environ.get(env_key):
                data[field] = os.environ[env_key]
        return cls(**data)

    @property
    def api_key_masked(self) -> str:
        if not self.deepseek_api_key:
            return "<未配置>"
        k = self.deepseek_api_key
        return f"{k[:4]}***{k[-4:]}" if len(k) > 8 else "***"
