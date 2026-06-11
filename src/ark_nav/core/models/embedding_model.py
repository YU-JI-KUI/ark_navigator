"""Embedding 模型部署"""
import logging
import os
import numpy as np
from typing import List
from ray import serve
from ark_nav.config import settings
from ark_nav.core.utils.nav_logger import setup_logging, propagate_trace

# GPU 副本配置：GPU 是稀缺资源，min/max 都需要独立控制
# target=50 看似很高，但配合 @serve.batch(max_batch_size=32) 实际是"1.5 个 GPU batch 在排队"
_EMBEDDING_MIN_REPLICAS = int(os.getenv("EMBEDDING_MIN_REPLICAS", 2))
_EMBEDDING_MAX_REPLICAS = int(os.getenv("EMBEDDING_MAX_REPLICAS", 4))


@serve.deployment(
    # 部署名保留 "rag-models" 以避免影响生产 Ray 集群中的部署标识与历史指标
    name="rag-models",
    ray_actor_options={
        "num_gpus": 0.5 if settings.use_gpu else 0,
        "num_cpus": 0 if settings.use_gpu else 1,
    },
    autoscaling_config={
        "min_replicas": _EMBEDDING_MIN_REPLICAS,
        "max_replicas": _EMBEDDING_MAX_REPLICAS,
        "target_num_ongoing_requests_per_replica": 50,
    },
)
class EmbeddingModelDeployment:
    """Embedding 模型 Ray Serve 部署"""

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        import torch

        setup_logging()
        logger = logging.getLogger(__name__)
        # USE_GPU=true 但 CUDA 不可用时必须 fail-fast：此前静默降级到 CPU，
        # 而副本仍按 GPU 模式申请资源（num_cpus=0），CPU 推理在 Ray 资源账本上
        # 隐形且无任何告警，问题被掩盖到性能排查时才暴露
        if settings.use_gpu and not torch.cuda.is_available():
            raise RuntimeError(
                "USE_GPU=true 但 torch.cuda.is_available()=False，拒绝静默降级到 CPU。"
                "请检查：1) 容器是否分到 GPU（K8s 需申请 nvidia.com/gpu，"
                "容器内 /dev/nvidia* 是否存在）；2) torch 是否为 CUDA 构建"
                "（torch.version.cuda 不应为 None）；纯 CPU 环境请显式设 USE_GPU=false"
            )
        self.device = "cuda" if settings.use_gpu else "cpu"
        logger.info(f"[Embedding] 加载模型到 {self.device}")
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
