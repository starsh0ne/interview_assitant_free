# interview-assist 项目约定

## 日志约定（log-first 技能，任何 AI 接手必读）

- **日志路径**：`logs/app.jsonl`，JSON Lines 格式，一行一条完整 JSON。
- **必填字段**：`ts` `level` `module` `location` `code` `trace_id` `msg`。
- **error 对象**：`level=ERROR` 时必须带 `error.type` / `error.message` / `error.stack`。
- **trace_id**：一次采集会话一个 trace_id，全链路贯穿（音频采集→VAD→转写→AI 分析→UI 显示）。
- **脱敏**：API Key、手机号、身份证等敏感信息不得入日志。

排错入口（AI 接到功能问题先自己查日志，不要问用户要）：
```bash
python <log-first 技能目录>/scripts/loggrep.py --dir logs --level ERROR --stats
python <log-first 技能目录>/scripts/loggrep.py --dir logs --keyword "关键词"
python <log-first 技能目录>/scripts/loggrep.py --dir logs --trace-id <trace_id>
```

详细规范见本地已安装的 `log-first` 技能文档。

## 运行

```bash
uv sync              # 安装依赖
uv run python app/main.py   # 启动（需先配置 DEEPSEEK_API_KEY）
```
