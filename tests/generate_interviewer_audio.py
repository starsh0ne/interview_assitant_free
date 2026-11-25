"""生成模拟面试官提问录音（edge-tts 中文语音）。

产出 tests/interviewer_audio/q01.mp3 ... q05.mp3，用于播放测试环回采集→转写→AI 全链路。
需要联网（edge-tts 使用微软在线语音）。

用法：
    .venv/Scripts/python.exe tests/generate_interviewer_audio.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import edge_tts

OUT_DIR = Path(__file__).resolve().parent / "interviewer_audio"
VOICE = "zh-CN-YunxiNeural"   # 男声，接近面试官语气
RATE = "-8%"                  # 稍慢，便于转写

QUESTIONS = [
    "请先做一个简单的自我介绍，重点说说你的技术背景。",
    "你在简历里提到做过 RAG 系统，能讲讲检索准确率是怎么优化的吗？",
    "如果面试官问你，FastAPI 和 Flask 有什么区别，你会怎么回答？",
    "说说你遇到过最难的技术问题，以及你是怎么解决的。",
    "你对我们这个岗位有什么期待？反问一个问题吧。",
]


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, q in enumerate(QUESTIONS, 1):
        path = OUT_DIR / f"q{i:02d}.mp3"
        if path.exists():
            print(f"[跳过] {path.name} 已存在")
            continue
        communicate = edge_tts.Communicate(q, VOICE, rate=RATE)
        await communicate.save(str(path))
        print(f"[生成] {path.name}  {q[:24]}...")
    (OUT_DIR / "questions.txt").write_text(
        "\n".join(f"q{i:02d}: {q}" for i, q in enumerate(QUESTIONS, 1)),
        encoding="utf-8",
    )
    print(f"\n完成，共 {len(QUESTIONS)} 段音频 → {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
