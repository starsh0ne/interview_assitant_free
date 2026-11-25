"""简历解析子包：PDF / Word → 纯文本上下文。"""
from .parser import parse_resume, supported_extensions

__all__ = ["parse_resume", "supported_extensions"]
