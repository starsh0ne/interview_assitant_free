"""
interview-assist 结构化日志配置（源自 log-first 技能模板，桌面端适配版）

在 main.py 启动时调用 configure_logging() 一次。
产出：logs/app.jsonl（JSON Lines），字段遵循 log-first schema：
  ts / level / module / location / code / trace_id / msg
依赖：structlog
"""
import logging
import uuid
from contextvars import ContextVar
from pathlib import Path

import structlog

# trace_id 上下文（每个采集会话/请求独立）
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "app.jsonl"


def normalize_schema(_logger, _method, event_dict):
    """把 structlog 默认键名对齐 log-first schema。

    structlog 26.x 输出：timestamp / info(小写) / event / lineno,pathname。
    log-first 要求：ts / INFO(大写) / msg / code=file:line / module / location / trace_id。
    """
    if "timestamp" in event_dict:
        event_dict["ts"] = event_dict.pop("timestamp")
    if "event" in event_dict:
        event_dict["msg"] = event_dict.pop("event")
    if "level" in event_dict:
        event_dict["level"] = str(event_dict["level"]).upper()
    # code = pathname:lineno（取文件名部分，保持相对路径可读性）
    pathname = event_dict.pop("pathname", "")
    lineno = event_dict.pop("lineno", "")
    func = event_dict.pop("func_name", "")
    if pathname or lineno:
        fname = Path(pathname).name if pathname else ""
        event_dict["code"] = f"{fname}:{lineno}" + (f" ({func})" if func else "")
    event_dict.setdefault("module", "-")
    event_dict.setdefault("location", "-")
    event_dict.setdefault("trace_id", "-")
    return event_dict


def configure_logging(log_path: str | None = None) -> None:
    """在应用启动时调用一次。"""
    path = Path(log_path) if log_path else LOG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,       # 注入 trace_id / location
            # 注：不使用 stdlib.filter_by_level —— 它在 structlog 26.x 与 WriteLoggerFactory 不兼容
            # （WriteLogger 无 disabled 属性）；级别过滤由下方 wrapper_class 完成。
            structlog.processors.TimeStamper(fmt="iso", utc=False),  # ts（带时区）
            structlog.processors.add_log_level,            # level
            structlog.processors.CallsiteParameterAdder(   # code: PATHNAME:LINENO
                {
                    structlog.processors.CallsiteParameter.PATHNAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                }
            ),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            normalize_schema,                              # 对齐 log-first 字段名
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.WriteLoggerFactory(
            file=path.open("a", encoding="utf-8")
        ),
        cache_logger_on_first_use=True,
    )


def get_logger():
    return structlog.get_logger()


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def bind_session_trace(trace_id: str, location: str = "session") -> None:
    """
    桌面端无 HTTP 请求上下文，采集会话开始时手动绑定 trace_id 与 location。
    工作线程中需调用本函数（contextvars 不跨线程自动继承）。
    """
    trace_id_var.set(trace_id)
    structlog.contextvars.bind_contextvars(trace_id=trace_id, location=location)


def unbind_session_trace() -> None:
    """清除当前上下文的 trace_id/location，防止线程池复用导致串线。"""
    structlog.contextvars.unbind_contextvars("trace_id", "location")
    trace_id_var.set("-")
