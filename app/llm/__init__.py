"""LLM 抽象层：通用接口 + 具体实现（当前 DeepSeek）。"""
from .base import BaseLLM, AnswerRequest
from .deepseek import DeepSeekLLM

__all__ = ["BaseLLM", "AnswerRequest", "DeepSeekLLM"]
