from typing import List, Dict, Any, Optional, Tuple

import faiss

from ark_nav.core.utils.nav_logger import get_logger, remote_with_trace

logger = get_logger(__name__)


class DenseRetriever:
    """基于 FAISS 的稠密向量检索器"""

    def __init__(self, embedding_model_handle):
        self.embedding_model_handle = embedding_model_handle
        self.dense_index: Optional[faiss.Index] = None
        self.chains: List[Dict[str, Any]] = []

    async def build_index(self, chains: List[Dict[str, Any]]):
        """构建向量索引（双缓冲：在临时变量里建好后一次性原子替换，避免热更新时短暂查空索引）"""
        texts = [c.get("text", "") for c in chains]

        logger.info("构建Dense索引...")
        embeddings = await remote_with_trace(
            self.embedding_model_handle.batch_encode,
            texts,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        new_dense_index = faiss.IndexFlatIP(embeddings.shape[1])
        new_dense_index.add(embeddings.astype("float32"))

        # 一次性原子替换两个字段（Python 引用赋值是 GIL 保护下的原子操作）
        self.chains = chains
        self.dense_index = new_dense_index

        logger.info(f"索引构建完成: {len(chains)}条")

    async def search(
        self, query: str, top_k: int = 5, recall_k: int = 10
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Dense 召回，返回 top_k 结果"""
        if not self.chains:
            return []

        query_emb = await self.embedding_model_handle.encode.remote(query)
        k = min(recall_k, len(self.chains))
        sims, idxs = self.dense_index.search(query_emb, k)

        results = [
            (self.chains[int(idx)], float(sim))
            for sim, idx in zip(sims[0], idxs[0])
        ]
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
