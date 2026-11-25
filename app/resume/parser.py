"""简历解析：PDF / Word → 纯文本，作为 AI 回答的上下文。

- PDF：pypdf
- Word：python-docx（.docx）；老式 .doc 不支持，给出清晰提示
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from app.logging_conf import get_logger

MODULE = "resume"


def supported_extensions() -> list[str]:
    return [".pdf", ".docx"]


def parse_resume(path: str | Path) -> str:
    """解析简历文件为纯文本。失败抛 ValueError（含可读原因）。"""
    p = Path(path)
    log = get_logger()
    start = time.perf_counter()
    log.info("简历解析开始", module=MODULE, location="parse_resume",
             status="start", file_ext=p.suffix.lower())

    if not p.exists():
        raise ValueError(f"文件不存在: {p}")
    ext = p.suffix.lower()
    if ext not in supported_extensions():
        if ext == ".doc":
            raise ValueError("不支持老式 .doc 格式，请先另存为 .docx")
        raise ValueError(f"不支持的简历格式: {ext}（支持 PDF / DOCX）")

    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        else:
            from docx import Document
            doc = Document(str(p))
            parts = [para.text for para in doc.paragraphs if para.text.strip()]
            # 表格内容（简历常见）
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
            text = "\n".join(parts)

        text = text.strip()
        if not text:
            raise ValueError("简历文件内容为空或无法提取文字（扫描版 PDF 需先做 OCR）")

        # 截断到合理长度，避免撑爆 LLM 上下文
        max_chars = 12000
        if len(text) > max_chars:
            text = text[:max_chars]

        log.info("简历解析完成", module=MODULE, location="parse_resume",
                 status="success", duration_ms=int((time.perf_counter()-start)*1000),
                 text_len=len(text))
        return text
    except ValueError:
        raise
    except Exception as e:
        log.error("简历解析失败", module=MODULE, location="parse_resume",
                  status="fail", error={"type": type(e).__name__, "message": str(e),
                                        "stack": traceback.format_exc()})
        raise ValueError(f"简历解析失败: {e}") from e
