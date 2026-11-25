# 模拟面试测试（验证全链路）

用于验证「系统输出环回采集 → 转写 → DeepSeek 分析 → 悬浮窗显示」全链路，无需真人面试官。

## 准备（一次性）

```bash
cd <项目目录>
# 生成 5 段模拟面试官提问录音（联网，edge-tts 中文男声）
.venv/Scripts/python.exe tests/generate_interviewer_audio.py
```

产出 `tests/interviewer_audio/q01.mp3 ~ q05.mp3`，内容见 `questions.txt`。

## 测试步骤

1. **启动主程序**：双击项目根目录 `启动面试辅助.bat`（或手动运行 `.venv/Scripts/python.exe app/main.py`）
2. **设置面板**：上传一份简历 → 选思考强度（建议"低"）→ 点「开始辅助」
3. **确认悬浮窗**显示「辅助中 · 请开始面试」
4. **另开一个终端**，播放模拟面试官提问：
   ```bash
   cd <项目目录>
   .venv/Scripts/python.exe tests/play_interviewer.py
   # 或只播一段：加 --only 1
   # 或循环播放：加 --loop
   ```
5. **观察悬浮窗**：应在几秒内显示识别到的面试官问题 + AI 要点回答
6. **模拟我方回答**：对着麦克风说话，悬浮窗标题应显示"识别到我方发言"（不触发 AI）

## 验证要点

| 检查项 | 预期 |
|---|---|
| 环回采集 | 播放录音时，日志出现 `module=audio, speaker=interviewer, VAD 切段完成` |
| 转写 | 日志 `module=transcriber`，识别文本与录音内容一致 |
| AI 触发 | 仅面试官提问触发 `module=llm`，我方回答不触发 |
| 悬浮窗 | 显示问题原文 + 3-5 条要点式回答 |
| trace_id | 同一次提问的采集/转写/AI/UI 日志 trace_id 一致 |

## 出问题时排错（AI 自主）

```bash
# 看错误统计
.venv/Scripts/python.exe <log-first 技能目录>/scripts/loggrep.py --dir logs --level ERROR --stats
# 拉某次提问的完整链路（把 trace_id 从悬浮窗标题取）
.venv/Scripts/python.exe <log-first 技能目录>/scripts/loggrep.py --dir logs --trace-id <trace_id>
```

## 注意

- 系统音量调到中等，确保扬声器/耳机确实在播放（环回只抓"正在播放"的声音）
- 如果用耳机，注意环回抓的是"耳机"设备而非"扬声器"，设置面板里要选对系统输出设备
- 段间默认停顿 2 秒，给 VAD 切段和 AI 分析留时间；若识别不完整可加大 `--gap 4`
