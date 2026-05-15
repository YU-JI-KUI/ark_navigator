"""Embedding 模型部署"""
import logging
import os
import numpy as np
from typing import List
from ray import serve
from ark_nav.config import settings
from ark_nav.core.utils.nav_logger import setup_logging, propagate_trace

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 2))


@serve.deployment(
    name="rag-models",
    ray_actor_options={
        "num_gpus": 0.5 if settings.use_gpu else 0,
        "num_cpus": 0 if settings.use_gpu else 1,
    },
    autoscaling_config={
        "min_replicas": MIN_REPLICAS,
        "max_replicas": 4,
        "target_num_ongoing_requests_per_replica": 50,
    },
)
class RAGModelDeployment:
    """Embedding 模型"""

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        import torch

        setup_logging()
        logger = logging.getLogger(__name__)
        self.device = "cuda" if torch.cuda.is_available() and settings.use_gpu else "cpu"
        logger.info("[Embedding] 加载模型到 %s", self.device)
        self.embedding_model = SentenceTransformer(
            settings.embedding_model,
            device=self.device,
        )
        logger.info("[Embedding] 模型加载完成")

    @serve.batch(
        max_batch_size=settings.embedding_batch_size,
        batch_wait_timeout_s=settings.batch_wait_timeout_ms / 1000.0,
    )
    async def encode(self, texts: List[str] | str) -> List[np.ndarray] | np.ndarray:
        """向量化文本（Ray Serve 自动批处理）"""
        internal_batch = min(len(texts), 128)
        embeddings = self.embedding_model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=internal_batch,
        ).astype("float32")
        return [embeddings[i : i + 1] for i in range(len(texts))]

    @propagate_trace
    async def batch_encode(
        self,
        texts: List[str],
        batch_size: int,
        show_progress_bar: bool = False,
        normalize_embeddings: bool = True,
    ):
        """向量化文本（批量）"""
        return self.embedding_model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=show_progress_bar,
        ).astype("float32")
