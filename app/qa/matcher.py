"""题库语义匹配：问题向量与题库问题向量做余弦相似度，超阈值即命中。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.logging_conf import get_logger
from app.qa.embedder import Embedder
from app.qa.store import QAEntry, QAStore

MODULE = "qa.matcher"


@dataclass
class QAMatch:
    entry: QAEntry
    score: float


class QAMatcher:
    def __init__(self, store: QAStore, embedder: Embedder, threshold: float):
        self.store = store
        self.embedder = embedder
        self.threshold = threshold
        self._log = get_logger()

    def _ensure_vectors(self, resume_text: str, entries: list[QAEntry], dim: int) -> None:
        """题目向量缺失或维度不符时补齐并落盘，下次启动免重算。"""
        stale = [i for i, e in enumerate(entries) if len(e.vector) != dim]
        if not stale:
            return
        vectors = self.embedder.embed([entries[i].question for i in stale])
        for i, vector in zip(stale, vectors):
            entries[i].vector = vector.tolist()
        self.store.save(resume_text, entries)
        self._log.info("题库向量已补齐", module=MODULE, location="QAMatcher._ensure_vectors",
                       status="success", count=len(stale), dim=dim)

    def match(self, resume_text: str, question: str) -> QAMatch | None:
        entries = self.store.load(resume_text)
        if not entries:
            return None

        query = self.embedder.embed([question])[0]
        self._ensure_vectors(resume_text, entries, len(query))
        matrix = np.asarray([e.vector for e in entries], dtype=np.float32)
        scores = matrix @ query
        idx = int(np.argmax(scores))
        score = float(scores[idx])

        self._log.info("题库相似度匹配", module=MODULE, location="QAMatcher.match",
                       status="success", question_len=len(question),
                       top_score=round(score, 4), threshold=self.threshold,
                       matched_id=entries[idx].id, entry_count=len(entries))

        if score >= self.threshold:
            return QAMatch(entry=entries[idx], score=score)
        return None
