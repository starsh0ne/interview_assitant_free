"""按简历内容哈希隔离的本地题库存储。

目录结构：qa_store/<简历SHA256前16位>/entries.json
题库属于个人隐私数据，已加入 .gitignore，不入库。
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.logging_conf import get_logger

MODULE = "qa.store"


@dataclass
class QAEntry:
    id: str
    question: str
    answer: str
    opener: str = ""
    points: list[str] = field(default_factory=list)
    tag: str = ""
    vector: list[float] = field(default_factory=list)


def resume_hash(resume_text: str) -> str:
    """简历内容哈希：统一换行并去首尾空白，避免复制/换行差异导致分库。"""
    normalized = resume_text.replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_answer(answer: str) -> tuple[str, list[str]]:
    """答案文本 → 首行结论 + 要点列表。兼容 -/•/1. 等前缀。"""
    lines = [ln.strip() for ln in answer.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return "", []
    opener = re.sub(r"^[-•*]\s*", "", lines[0])
    points = []
    for ln in lines[1:]:
        ln = re.sub(r"^\d+[.、)]\s*", "", ln)
        ln = re.sub(r"^[-•*]\s*", "", ln)
        if ln:
            points.append(ln)
    return opener, points


class QAStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._log = get_logger()

    def namespace(self, resume_text: str) -> Path:
        """按简历哈希返回（并创建）独立题库目录。"""
        path = self.root / resume_hash(resume_text)[:16]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def entries_path(self, resume_text: str) -> Path:
        return self.namespace(resume_text) / "entries.json"

    def load(self, resume_text: str) -> list[QAEntry]:
        path = self.entries_path(resume_text)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [QAEntry(**item) for item in data]
        except Exception as exc:
            self._log.warning("题库读取失败，按空库处理", module=MODULE,
                              location="QAStore.load", status="fail",
                              error=f"{type(exc).__name__}: {exc}")
            return []

    def save(self, resume_text: str, entries: list[QAEntry]) -> None:
        path = self.entries_path(resume_text)
        path.write_text(
            json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, resume_text: str, question: str, answer: str,
            tag: str = "", vector: list[float] | None = None) -> QAEntry:
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空")
        entries = self.load(resume_text)
        opener, points = parse_answer(answer)
        entry = QAEntry(
            id=uuid.uuid4().hex[:8],
            question=question,
            answer=answer.strip(),
            opener=opener,
            points=points,
            tag=tag,
            vector=vector or [],
        )
        entries.append(entry)
        self.save(resume_text, entries)
        self._log.info("题库新增条目", module=MODULE, location="QAStore.add",
                       status="success", entry_id=entry.id,
                       resume_hash=resume_hash(resume_text)[:16])
        return entry

    def delete(self, resume_text: str, entry_id: str) -> None:
        entries = [e for e in self.load(resume_text) if e.id != entry_id]
        self.save(resume_text, entries)
        self._log.info("题库删除条目", module=MODULE, location="QAStore.delete",
                       status="success", entry_id=entry_id)
