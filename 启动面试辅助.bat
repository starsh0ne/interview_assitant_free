@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   interview-assist 面试实时辅助工具
echo ============================================
echo.

REM ---------- 模型缓存目录（项目内，避免污染用户目录） ----------
if "%HF_HOME%"=="" set "HF_HOME=%~dp0.models"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"
echo [OK] 模型缓存目录: %HF_HOME%

REM ---------- 1. 定位 uv ----------
set "UV_CMD="
where uv >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "UV_CMD=uv"
) else if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
) else (
    echo [错误] 未找到 uv 包管理器。请先安装：
    echo   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)
echo [OK] uv: !UV_CMD!

REM ---------- 2. 环境变量检查 ----------
if "%DEEPSEEK_API_KEY%"=="" (
    echo [警告] 未检测到 DEEPSEEK_API_KEY 环境变量。
    echo   可在启动后的设置面板中手动输入 API Key。
) else (
    echo [OK] DEEPSEEK_API_KEY 已配置: %DEEPSEEK_API_KEY:~0,6%***%DEEPSEEK_API_KEY:~-4%
)

REM ---------- 3. 虚拟环境 ----------
if not exist ".venv\Scripts\python.exe" (
    echo [安装] 创建 Python 3.13 虚拟环境...
    "!UV_CMD!" venv --python 3.13 .venv
    if !ERRORLEVEL! NEQ 0 ( echo [错误] venv 创建失败 & pause & exit /b 1 )
)
set "PY=.venv\Scripts\python.exe"

REM ---------- 4. 依赖检查（缺关键包则安装） ----------
"!PY!" -c "import PySide6, soundcard, faster_whisper, openai, pypdf, docx, structlog" >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo [安装] 首次运行，安装依赖（约 1-2 分钟）...
    if not exist "requirements.lock.txt" (
        echo [错误] 缺少 requirements.lock.txt
        pause
        exit /b 1
    )
    "!UV_CMD!" pip install --python .venv\Scripts\python.exe -r requirements.lock.txt
    if !ERRORLEVEL! NEQ 0 ( echo [错误] 依赖安装失败 & pause & exit /b 1 )
)
echo [OK] 依赖就绪

REM ---------- 5. Whisper 模型预下载 ----------
if not exist ".models_prepared" (
    echo [下载] 首次运行，下载 faster-whisper small 模型（约 500MB，需联网）...
    echo   若下载失败并报代理错误，请先设置可用代理，例如：
    echo   set HTTPS_PROXY=http://127.0.0.1:7897
    "!PY!" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); print('[OK] 模型下载完成')"
    if !ERRORLEVEL! EQU 0 (
        echo done > .models_prepared
    ) else (
        echo [警告] 模型下载失败，可能是代理不通。可稍后手动重试：
        echo   .venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small',device='cpu',compute_type='int8')"
    )
) else (
    echo [OK] Whisper 模型已就绪
)

REM ---------- 6. 启动 ----------
echo.
echo [启动] 正在启动面试辅助工具...
echo   设置面板：上传简历 -^> 选强度 -^> 点"开始辅助"
echo   悬浮窗：拖动移动，双击切换置顶
echo.
"!PY!" -m app.main

if !ERRORLEVEL! NEQ 0 (
    echo.
    echo [错误] 应用异常退出，请查看 logs\app.jsonl 或把此窗口内容发给 AI 排错。
    pause
)
endlocal
