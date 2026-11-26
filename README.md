# interview-assist · 面试实时辅助工具

Windows 桌面端，用于**线上面试实时辅助**：双源音频采集（区分面试官提问与我方回答）→ 本地语音转文字 → DeepSeek 分析问题 → 半透明置顶悬浮窗显示要点式回答。

**最新变更（2026-11-26）**：
- 新增本地题库：按简历哈希隔离，语义相似问题直接回放预设答案，**零 AI 调用**
- 首次运行需联网下载约 90MB 的中文向量模型（bge-small-zh-v1.5 ONNX），之后完全离线
- 阈值调参脚本 + 命中相似度标注，宝洁八大问改写版实测 16/16 命中、0 误命中

**（2026-11-26）**：
- 修复上传简历后界面消失：两个窗口都是 `Qt.Tool`，Qt 默认的 `quitOnLastWindowClosed` 会在模态文件对话框关闭后误判为"主窗口已关闭"而退出进程；已关闭该行为，退出改由设置面板「退出程序」按钮显式触发
- 新增 `tests/verify_upload.py` 回归验证上传后进程存活且速查卡正常生成

**（2026-11-25）**：
- 模型切换为官方 `deepseek-flash`（DeepSeek-V4.1-Flash）；低/中档关闭思考链，高档启用深度思考
- 新增一键启动脚本 `启动面试辅助.bat`（自动建环境/装依赖/启动）
- 新增模拟面试官录音与播放脚本，见 `tests/README_模拟面试测试.md`
- Whisper small 模型与 5 段模拟提问 MP3 已随仓库分发；大文件通过 Git LFS 管理
- 悬浮窗与设置面板启用单向隐身：本地可见可拖动，截屏 / 录屏 / 会议共享抓不到
- 任务栏静默：设置面板不再占用任务栏；一键脚本启动后自动隐藏 cmd 窗口（异常退出时自动恢复显示）

## 功能

- **LLM 通用接口**：`BaseLLM` 抽象层 + DeepSeek 实现（OpenAI 兼容协议），换模型只需新增一个实现
- **双源音频采集**：麦克风=我方回答，WASAPI 环回=面试官提问（无需虚拟声卡）
- **VAD 静音切段**：说话停顿 1.5 秒自动切段，异步转写不阻塞
- **本地转写**：faster-whisper（small 模型，中文，离线可用）
- **要点式回答**：3-5 条 bullet + 一句话开场，便于快速扫读
- **思考强度**：低 / 中 / 高三档，默认低
- **简历前置上传**：开始前必须上传 PDF / DOCX 简历，作为 AI 回答上下文
- **半透明置顶悬浮窗**：可拖动、双击切换置顶
- **单向隐身**：悬浮窗与设置面板本地可见，但被排除出截屏 / 录屏 / 会议共享（Win32 `WDA_EXCLUDEFROMCAPTURE`）
- **任务栏静默**：两个窗口均为 `Qt.Tool`，不显示任务栏图标；启动脚本在应用启动后隐藏 cmd 黑窗，仅保留 `logs/app.jsonl` 排错
- **本地题库**：按简历 SHA256 分目录隔离；问题语义向量匹配，命中直接回放答案（悬浮窗标注相似度与原题），未命中才走 AI
- **结构化日志**：遵循 log-first 规范，AI 可按字段自主排错

## 安装

```bash
git clone https://github.com/starsh0ne/interview_assitant_free.git
cd interview_assitant_free
git lfs install
git lfs pull          # 拉取 Whisper small 模型（约 460MB），必须执行

uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt
```

如未安装 Git LFS，请先安装：https://git-lfs.com 。未执行 `git lfs pull` 时，仓库里的 `model.bin` 只是指针文件，转写会失败。

## 配置

设置 DeepSeek API Key（二选一）：

```bash
# PowerShell
$env:DEEPSEEK_API_KEY = "sk-xxxxxxxx"
# 或在设置面板中直接输入（仅内存，不落盘）
```

题库命中阈值可在 `config.local.json` 覆盖（不建该文件则用默认值 0.60）：

```json
{ "qa_similarity_threshold": 0.60 }
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

**双击 `启动面试辅助.bat`** —— 自动检查环境、依赖、模型并启动。模型已随仓库提供；首次运行仍会联网安装 Python 依赖，Whisper 模型无需再次下载（前提是已执行 `git lfs pull`）。

手动运行：
```bash
.venv/Scripts/python.exe app/main.py
```

使用流程：
1. 设置面板上传简历（PDF/DOCX）—— 题库自动切换到该简历的独立空间
2. 在本地题库区点「导入宝洁八大问」快速建库，再逐条把答案换成自己的回答（第一行结论，后续每行要点）
3. 选思考强度（默认低）、音频设备
4. 填 API Key（如未设环境变量；题库命中时不需要）
5. 点「开始辅助」：相似问题直接回放题库答案，其他问题才走 AI
6. 点「停止」结束辅助；点「退出程序」关闭应用（窗口不占任务栏，需用此按钮退出）

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
├── qa/
│   ├── embedder.py    本地语义向量（fastembed / bge-small-zh ONNX）
│   ├── store.py       按简历 SHA256 隔离的题库 CRUD
│   ├── matcher.py     余弦相似度匹配
│   └── pg8.py         宝洁八大问样例
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

题库验证与调参：

```bash
.venv/Scripts/python.exe tests/verify_qa.py          # 哈希隔离 / 语义命中 / 跳过 AI
.venv/Scripts/python.exe tests/tune_qa_threshold.py  # 宝洁八问 16 条改写表达，扫描各阈值命中率
```

## 已知限制

- `.doc` 老式 Word 不支持，需另存为 `.docx`
- 扫描版 PDF 需先 OCR（无法提取文字）
- 模型已随仓库分发，但依赖 Git LFS；未拉取 LFS 对象时 `model.bin` 为指针文件，需先执行 `git lfs pull`
- 系统输出环回依赖声卡驱动支持 WASAPI loopback；无输出设备时仅采麦克风
- 思考强度"高"会增加 token 消耗与延迟，实时场景建议用"低"
- 隐身是**窗口级排除**，不是只针对腾讯会议：开启后任何截图 / 录屏 / 共享都抓不到这两个窗口；API 失败时界面会显示「隐身不可用」告警
- 题库答案为预设文本，命中时不做二次 AI 润色；问题表述差异过大时会走 AI 现场生成
- 阈值 0.60 是宝洁八问 16 条改写的实测值，换行业/岗位题型后需重新跑调参脚本
- `qa_store/` 与向量模型缓存均已加入 `.gitignore`，不会上传题库隐私数据
