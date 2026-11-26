"""本地中文语义向量：fastembed + bge-small-zh-v1.5（ONNX，CPU）。

完全本地推理，不调用 AI API；向量做 L2 归一化，可直接点积算余弦相似度。
"""
from __future__ import annotations

import threading

import numpy as np

from app.core.config import PROJECT_ROOT, AppConfig
from app.logging_conf import get_logger

MODULE = "qa.embedder"


class Embedder:
    """懒加载模型；模型跨实例共享，避免流水线与设置面板各加载一份。"""

    _shared_model = None
    _shared_lock = threading.RLock()

    def __init__(self, config: AppConfig):
        self.config = config
        self._log = get_logger()

    @property
    def cache_dir(self) -> str:
        return str(PROJECT_ROOT / ".models" / "fastembed")

    def _get_model(self):
        if Embedder._shared_model is None:
            with Embedder._shared_lock:
                if Embedder._shared_model is None:
                    from fastembed import TextEmbedding

                    self._log.info("加载语义向量模型", module=MODULE,
                                   location="Embedder._get_model", status="start",
                                   model=self.config.qa_embed_model)
                    Embedder._shared_model = TextEmbedding(
                        model_name=self.config.qa_embed_model,
                        cache_dir=self.cache_dir,
                    )
                    self._log.info("语义向量模型就绪", module=MODULE,
                                   location="Embedder._get_model", status="success")
        return Embedder._shared_model

    def embed(self, texts: list[str]) -> np.ndarray:
        """返回 (n, dim) 的归一化 float32 向量。"""
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        with Embedder._shared_lock:
            vectors = np.asarray(list(self._get_model().embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def warmup(self) -> None:
        self.embed(["语义向量预热"])
