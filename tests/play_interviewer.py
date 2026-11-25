"""播放模拟面试官提问录音，用于测试环回采集 → 转写 → AI 全链路。

播放时请：
1. 先在主程序点"开始辅助"（悬浮窗显示"辅助中"）
2. 系统音量调到中等，确保扬声器/耳机正在播放
3. 运行本脚本播放问题（WASAPI 环回会抓到系统输出）
4. 对着麦克风回答（模拟我方），观察悬浮窗

用法：
    .venv/Scripts/python.exe tests/play_interviewer.py            # 顺序播放全部，每段间隔 2 秒
    .venv/Scripts/python.exe tests/play_interviewer.py --loop     # 循环播放
    .venv/Scripts/python.exe tests/play_interviewer.py --only 1   # 只播第 1 段
    .venv/Scripts/python.exe tests/play_interviewer.py --gap 4    # 段间停顿 4 秒
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pygame

AUDIO_DIR = Path(__file__).resolve().parent / "interviewer_audio"


def play_file(path: Path) -> float:
    """播放单个 mp3，返回播放时长（秒）。"""
    pygame.mixer.init(frequency=44100)
    pygame.mixer.music.load(str(path))
    pygame.mixer.music.play()
    start = time.time()
    clock = pygame.time.Clock()
    while pygame.mixer.music.get_busy():
        clock.tick(20)
    return time.time() - start


def main():
    ap = argparse.ArgumentParser(description="播放模拟面试官提问录音")
    ap.add_argument("--loop", action="store_true", help="循环播放")
    ap.add_argument("--only", type=int, default=0, help="只播放指定编号（1-5）")
    ap.add_argument("--gap", type=float, default=2.0, help="段间停顿秒数（默认 2，给 VAD 切段和 AI 分析留时间）")
    ap.add_argument("--device", type=int, default=None, help="pygame 音频设备索引（默认 0）")
    args = ap.parse_args()

    files = sorted(AUDIO_DIR.glob("q*.mp3"))
    if not files:
        print(f"未找到录音文件，请先运行: .venv/Scripts/python.exe tests/generate_interviewer_audio.py")
        return
    if args.only:
        files = [f for f in files if f.stem == f"q{args.only:02d}"]
        if not files:
            print(f"没有第 {args.only} 段录音")
            return

    print(f"准备播放 {len(files)} 段，段间停顿 {args.gap} 秒")
    print("提示：确保主程序已点『开始辅助』，系统音量适中\n")

    while True:
        for f in files:
            print(f"▶ 播放 {f.name} ...", flush=True)
            dur = play_file(f)
            print(f"  完成（{dur:.1f}秒），停顿 {args.gap} 秒\n", flush=True)
            time.sleep(args.gap)
        if not args.loop:
            break
        print("--- 循环下一轮 ---\n")


if __name__ == "__main__":
    main()
