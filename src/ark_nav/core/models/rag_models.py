"""BGE-rerank 重排序模型部署"""
import os
import numpy as np
from typing import List
from ray import serve
from ark_nav.config import settings
from ark_nav.core.utils.nav_logger import setup_logging, get_logger

logger = get_logger(__name__)

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 2))


@serve.deployment(
    name="rag-models",
    ray_actor_options={
        "num_gpus": 0.5 if settings.use_gpu else 0,
        "num_cpus": 0 if settings.use_gpu else 1},
    autoscaling_config={
        "min_replicas": MIN_REPLICAS,
        "max_replicas": 4,
        "target_num_ongoing_requests_per_replica": 50
    }
)
class RAGModelDeployment:
    """BGE-rerank 重排序模型 & Embedding"""

    def __init__(self):
        from sentence_transformers import CrossEncoder, SentenceTransformer
        import torch
        setup_logging()
        self.device = "cuda" if torch.cuda.is_available() and settings.use_gpu else "cpu"
        logger.info(f"[Rerank] 加载模型到 {self.device}")
        self.rerank_model = CrossEncoder(settings.rerank_model, max_length=512, device=self.device)
        self.rerank_model.eval()
        logger.info(f"[Rerank] 模型加载完成")
        logger.info(f"[Embedding] 加载模型到 {self.device}")
        self.embedding_model = SentenceTransformer(
            settings.embedding_model,
            device=self.device
        )
        logger.info(f"[Embedding] 模型加载完成")

    async def rerank(self, pairs) -> List[float]:
        """重排序打分"""

        return self.rerank_model.predict(pairs)

    @serve.batch(
        max_batch_size=settings.embedding_batch_size,
        batch_wait_timeout_s=settings.batch_wait_timeout_ms / 1000.0
    )
    async def encode(self, texts: List[str] | str) -> List[np.ndarray] | np.ndarray:
        """向量化文本（Ray Serve 自动批处理）

        工作原理：
        1. 多个并发请求调用 encode(text)
        2. Ray Serve 自动收集：texts = [text1, text2, text3, ...]
        3. 批量编码后自动分发回各个请求

        参数：
            texts: Ray Serve 自动收集的文本列表

        返回：
            List[np.ndarray]: 每个文本的向量 (1, dim), Ray Serve 自动分发
        """
        internal_batch = min(len(texts), 128)

        embeddings = self.embedding_model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=internal_batch
        ).astype("float32")

        # 拆分为单个向量
        return [embeddings[i:i + 1] for i in range(len(texts))]

    async def batch_encode(self, texts: List[str], batch_size: int, show_progress_bar=False, normalize_embeddings=True):
        """向量化文本"""
        embeddings = self.embedding_model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=show_progress_bar
        ).astype("float32")
        return embeddings


if __name__ == "__main__":
    import ray
    import asyncio

    ray.init()
    serve.run(RAGModelDeployment.bind())

    async def test():
        handle = serve.get_deployment_handle("rag-models", "default")
        scores = await handle.rerank.remote(["世界", "再见"])
        logger.info(f"重排序分数: {scores}")

    asyncio.run(test())
