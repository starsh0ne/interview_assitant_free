# interview-assist · 面试实时辅助工具

Windows 桌面端，用于**线上面试实时辅助**：双源音频采集（区分面试官提问与我方回答）→ 本地语音转文字 → DeepSeek 分析问题 → 半透明置顶悬浮窗显示要点式回答。

**最新变更（2026-11-25）**：
- 模型切换为官方 `deepseek-flash`（DeepSeek-V4.1-Flash）；低/中档关闭思考链，高档启用深度思考
- 新增一键启动脚本 `启动面试辅助.bat`（自动建环境/装依赖/启动）
- 新增模拟面试官录音与播放脚本，见 `tests/README_模拟面试测试.md`

## 功能

- **LLM 通用接口**：`BaseLLM` 抽象层 + DeepSeek 实现（OpenAI 兼容协议），换模型只需新增一个实现
- **双源音频采集**：麦克风=我方回答，WASAPI 环回=面试官提问（无需虚拟声卡）
- **VAD 静音切段**：说话停顿 1.5 秒自动切段，异步转写不阻塞
- **本地转写**：faster-whisper（small 模型，中文，离线可用）
- **要点式回答**：3-5 条 bullet + 一句话开场，便于快速扫读
- **思考强度**：低 / 中 / 高三档，默认低
- **简历前置上传**：开始前必须上传 PDF / DOCX 简历，作为 AI 回答上下文
- **半透明置顶悬浮窗**：可拖动、双击切换置顶
- **结构化日志**：遵循 log-first 规范，AI 可按字段自主排错

## 安装

```bash
cd <项目目录>
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt
```

## 配置

设置 DeepSeek API Key（二选一）：

```bash
# PowerShell
$env:DEEPSEEK_API_KEY = "sk-xxxxxxxx"
# 或在设置面板中直接输入（仅内存，不落盘）
```

## 性能（实测 2026-11-25）

提问结束 → 首条结论上屏：**~3 秒内**（旧链路 6-8 秒）。优化组合：
- VAD 静音切段 1500→800ms，且 400ms 即提交**预转写**（与静音确认并行）
- whisper beam_size 5→1（CPU 提速 2-3 倍）
- DeepSeek **流式输出**：首行结论先上屏，要点逐条到达
- 三档思考强度：低/中 = `thinking:disabled`（0.4-0.8s 首 token）；高 = `thinking:enabled`+`effort:high`（深度换速度）
- 点"开始"即后台预热 whisper 模型与 API 连接
- 简历上传时后台生成 **AI 速查卡**（~300 字），此后每次提问只携带速查卡

回答风格：口述化分层——首句可直接照着说的结论 + 按问题复杂度自适应的要点行（事实题 0-1 行，设计题 3-5 行）。

## 运行（一键）

**双击 `启动面试辅助.bat`** —— 自动检查环境、依赖、模型并启动。首次运行会自动下载依赖与 Whisper 模型（需联网，约 500MB）。

手动运行：
```bash
.venv/Scripts/python.exe app/main.py
```

使用流程：
1. 设置面板上传简历（PDF/DOCX）
2. 选思考强度（默认低）、音频设备
3. 填 API Key（如未设环境变量）
4. 点「开始辅助」，悬浮窗显示识别与回答
5. 点「停止」结束

## 架构

```
app/
├── main.py            主入口，串联 UI/采集/流水线
├── pipeline.py        核心流水线（QObject 信号跨线程更新 UI）
├── core/
│   ├── config.py      配置（环境变量 + config.local.json）
│   └── models.py      数据结构（AudioSegment/Transcript/Answer，含 trace_id）
├── audio/
│   ├── capture.py     双源采集线程
│   ├── devices.py     设备枚举
│   ├── vad.py         能量阈值 VAD（纯逻辑，可单测）
│   └── transcriber.py faster-whisper 异步转写
├── llm/
│   ├── base.py        通用接口 + 日志包装 + 降级
│   └── deepseek.py    DeepSeek 实现 + 三档思考强度映射
├── resume/parser.py   PDF/DOCX 简历解析
├── ui/
│   ├── overlay.py     半透明置顶悬浮窗
│   └── settings.py    设置面板
└── logging_conf.py    log-first 结构化日志
```

## 排错（AI 自主）

接到功能问题时，AI 应先查日志而非让用户复制面板输出：

```bash
python <log-first 技能目录>/scripts/loggrep.py --dir logs --level ERROR --stats
python <log-first 技能目录>/scripts/loggrep.py --dir logs --trace-id <trace_id>
```

日志字段：`ts / level / module / location / code / trace_id / msg`，错误带 `error.type/message/stack`。

## 已知限制

- `.doc` 老式 Word 不支持，需另存为 `.docx`
- 扫描版 PDF 需先 OCR（无法提取文字）
- 首次转写会下载 faster-whisper 模型（small 约 500MB），需联网一次
- 系统输出环回依赖声卡驱动支持 WASAPI loopback；无输出设备时仅采麦克风
- 思考强度"高"会增加 token 消耗与延迟，实时场景建议用"低"
