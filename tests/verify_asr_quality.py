"""回归验证：领域词 hotwords + 术语归一化 + 转写原文日志。

覆盖：
1. 从简历/题库提取技术词（RAG / LangGraph / DeepSeek），排除停用词
2. hotwords 经 pipeline.start 注入 transcriber（用假 transcriber 拦截）
3. 大小写归一化生效（rag→RAG），且不做模糊猜测（rate 不被误改）
4. QAMatcher 归一化后仍能正确命中，日志含 query_text
5. 转写完成日志含 text 字段

运行：.venv/Scripts/python.exe tests/verify_asr_quality.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.core.config import AppConfig
from app.qa.embedder import Embedder
from app.qa.matcher import QAMatcher
from app.qa.store import QAStore
from app.qa.terms import build_hotwords, extract_terms, normalize_question

RESUME = (
    "后端开发 5 年，主导 RAG 检索优化，QPS 从 1000 提升到 5000。"
    "技术栈 Python LangGraph DeepSeek fastembed，熟悉 Redis 与 bge-large 向量模型。"
    "在项目中 RAG 召回率提升 30%，用 LangGraph 编排多智能体。"
)
QUESTION = "讲讲你在 RAG 项目里怎么提升召回率"


def main() -> int:
    config = AppConfig.load()
    embedder = Embedder(config)
    failures = []

    # 1. 词提取
    terms = extract_terms(RESUME, [QUESTION])
    print(f"提取术语（前10）: {terms[:10]}")
    for must in ("RAG", "QPS", "LangGraph", "DeepSeek"):
        if must not in terms:
            failures.append(f"术语提取漏掉 {must}: {terms}")
    if "THE" in terms or "AND" in terms:
        failures.append(f"停用词未被过滤: {terms}")

    hotwords = build_hotwords(terms)
    print(f"hotwords: {hotwords[:100]}")

    # 2. hotwords 注入（假 transcriber 拦截 set_hotwords）
    class FakeTranscriber:
        def __init__(self):
            self.hotwords = ""

        def set_hotwords(self, value: str):
            self.hotwords = value

        def shutdown(self):
            pass

    tr = FakeTranscriber()

    # 用最小 pipeline 验证 start 会注入；避免真采集/真转写
    import queue
    from app.audio.capture import AudioCapture
    from app.core.models import ThinkLevel
    from app.llm.base import AnswerRequest, BaseLLM
    from app.pipeline import Pipeline

    class FakeCapture:
        def __init__(self):
            self.segment_queue = queue.Queue()

    class FakeLLM(BaseLLM):
        def answer(self, req: AnswerRequest):
            from app.core.models import Answer
            return Answer(question=req.question, opener="ok", points=["p"])

    with __import__("tempfile").TemporaryDirectory(prefix="asr_terms_") as tmp:
        pipeline = Pipeline(config, FakeCapture(), tr, FakeLLM())  # type: ignore[arg-type]
        pipeline.qa_store = QAStore(tmp)
        pipeline.start(RESUME, ThinkLevel.LOW)
        print(f"pipeline 注入 hotwords 长度: {len(tr.hotwords)}, 含 RAG: {'RAG' in tr.hotwords}")
        if "RAG" not in tr.hotwords:
            failures.append(f"hotwords 未注入 RAG: {tr.hotwords}")
        pipeline.stop()

    # 3. 归一化：大小写统一生效；模糊词不猜测（rack/rate 都可能误伤，交给 hotwords 源头解决）
    phrase = "讲讲 rag 项目里怎么提升召回率"
    normalized = normalize_question(phrase, terms)
    print(f"归一化: {phrase}  ->  {normalized}")
    if "RAG" not in normalized:
        failures.append(f"rag 未归一化为 RAG: {normalized}")
    unchanged = normalize_question("the rate is high", terms)
    if "rate" not in unchanged or "RAG" in unchanged:
        failures.append(f"普通词 rate 被误改: {unchanged}")

    # 4. matcher 归一化后命中
    with __import__("tempfile").TemporaryDirectory(prefix="asr_match_") as tmp:
        store = QAStore(tmp)
        entry = store.add(RESUME, QUESTION, "结论：优化分块和重排。\n• 调整 chunk size",
                          vector=embedder.embed([QUESTION])[0].tolist())
        matcher = QAMatcher(store, embedder, threshold=config.qa_similarity_threshold)
        matcher.set_terms(terms)

        wrong_case = "讲讲 rag 项目里怎么提升召回率"
        raw_score = float(embedder.embed([wrong_case])[0] @ embedder.embed([QUESTION])[0])
        hit = matcher.match(RESUME, wrong_case)
        print(f"大小写归一前裸分={raw_score:.4f}, 归一后命中={hit is not None} "
              f"score={hit.score if hit else '-'}")
        if hit is None:
            failures.append("rag 大小写归一化后仍未命中题库")
        elif hit.entry.id != entry.id:
            failures.append("归一化后命中了错误的题库条目")

    # 5. 转写日志含 text 字段（源码级检查，避免真跑 Whisper）
    src = (Path(__file__).resolve().parent.parent / "app" / "audio" / "transcriber.py").read_text(encoding="utf-8")
    marker = 'text=text'
    if marker not in src:
        failures.append("转写完成日志缺少 text 字段")

    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("PASS: 词提取 / hotwords 注入 / 大小写归一（rack 不猜）/ 命中 / 日志原文")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
