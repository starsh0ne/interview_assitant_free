"""领域术语提取与误转归一化。

用途：
1. 从简历全文 + 题库问题自动提取英文技术词（RAG / LangGraph / DeepSeek…），
   注入 Whisper 的 hotwords，减少专有名词误转（如 RAG → rack）。
2. 语义匹配前对转写文本做轻量归一化（大小写统一 + 近编辑距离纠正），
   即使 Whisper 仍转错，也能在向量匹配阶段兜底。

设计约束：
- 只纠正「词表里确实存在」的术语，不凭空替换普通词，避免误伤。
- 归一化只用于向量计算，不改上屏原文（用户看到的仍是面试官原话）。
"""
from __future__ import annotations

import re
from collections import Counter

MODULE = "qa.terms"

# 常见英文虚词/日常词，不作为技术术语注入（避免 hotwords 稀释与误纠正）
_STOPWORDS = {
    "THE", "AND", "FOR", "WITH", "THIS", "THAT", "FROM", "YOU", "ARE", "NOT",
    "BUT", "ALL", "CAN", "HAS", "HAVE", "WILL", "OUR", "YOUR", "ITS", "WAS",
    "WERE", "HOW", "WHAT", "WHEN", "WHERE", "WHY", "WHO", "WHICH", "SOME",
    "ANY", "MORE", "MOST", "OTHER", "INTO", "ABOUT", "THAN", "THEN", "THEY",
    "THEM", "THEIR", "OURS", "YES", "OK", "OKAY", "ONE", "TWO", "THREE",
    "I", "A", "AN", "IS", "IN", "ON", "AT", "TO", "OF", "OR", "AS", "BY",
    "BE", "DO", "IT", "WE", "MY", "ME", "US", "HE", "SHE", "HI", "THE",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,19}")

def _is_term(token: str) -> bool:
    """判断一个英文 token 是否像技术术语（缩写或驼峰）。"""
    if token.upper() in _STOPWORDS:
        return False
    if len(token) < 2 or len(token) > 20:
        return False
    # 全大写缩写：RAG / QPS / SQL / LLM（至少 2 个字母，可含数字）
    if token.isupper() and any(c.isalpha() for c in token):
        return True
    # 驼峰：至少两处大写开头，如 LangGraph / DeepSeek / PyTorch
    upper_count = sum(1 for c in token if c.isupper())
    if upper_count >= 2 and token[0].isupper():
        return True
    return False


def extract_terms(resume_text: str, questions: list[str], max_count: int = 30) -> list[str]:
    """从简历全文 + 题库问题提取技术词，按出现频次降序返回。

    频次高的更可能是本人反复强调的核心技术，注入 hotwords 收益最大。
    去重按小写，输出保留原始大小写（Whisper 对大小写不敏感，保留便于界面查看）。
    """
    sources = [resume_text] + list(questions)
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for text in sources:
        if not text:
            continue
        for token in _TOKEN_RE.findall(text):
            if not _is_term(token):
                continue
            key = token.lower()
            counts[key] += 1
            display.setdefault(key, token)
    # 频次相同按字母序，保证结果稳定可测
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [display[key] for key, _ in ranked[:max_count]]


def build_hotwords(terms: list[str], max_count: int = 30) -> str:
    """拼成 faster-whisper 的 hotwords 字符串。空词表返回空串（调用方传 None）。"""
    return " ".join(terms[:max_count])


def normalize_question(text: str, terms: list[str]) -> str:
    """对转写文本做术语归一化，只改词表命中的英文 token。

    - 大小写统一：rag / Rag / RAG → 词表中的标准写法（RAG）
    - 近编辑距离纠正：rack → RAG（距离 2），rate 不会被改成 RAG（距离 3）
    - 词表为空或未命中则原样返回，零副作用
    """
    if not text or not terms:
        return text
    by_lower = {t.lower(): t for t in terms}

    def repl(match: re.Match) -> str:
        token = match.group(0)
        low = token.lower()
        # 1) 精确匹配（忽略大小写）
        if low in by_lower:
            return by_lower[low]
        # 2) 不做模糊纠正：rack→RAG 与 rate→RAG 的字符串距离完全相同，
        #    无法靠规则区分；强行纠正会误伤普通英文词。只保留大小写归一化。
        return token

    return _TOKEN_RE.sub(repl, text)
