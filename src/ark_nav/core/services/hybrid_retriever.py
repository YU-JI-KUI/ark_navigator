from typing import List, Dict, Any, Optional, Tuple

import faiss
from rank_bm25 import BM25Okapi

from ark_nav.core.utils.nav_logger import get_logger, remote_with_trace

logger = get_logger(__name__)


class HybridRetriever:
    """混合召回检索器：Dense（FAISS 向量）+ Sparse（BM25 关键词）"""

    def __init__(self, embedding_model_handle):
        self.embedding_model_handle = embedding_model_handle
        self.dense_index: Optional[faiss.Index] = None
        self.sparse_index: Optional[BM25Okapi] = None
        self.chains: List[Dict[str, Any]] = []

    async def build_index(self, chains: List[Dict[str, Any]]):
        """构建双索引"""
        self.chains = chains
        texts = [c.get("text", "") for c in chains]

        logger.info("构建Dense索引...")
        embeddings = await remote_with_trace(
            self.embedding_model_handle.batch_encode,
            texts,
            batch_size=32,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        self.dense_index = faiss.IndexFlatIP(embeddings.shape[1])
        self.dense_index.add(embeddings.astype("float32"))

        logger.info("构建Sparse索引...")
        tokenized_corpus = [self._extract_keywords(text) for text in texts]
        self.sparse_index = BM25Okapi(tokenized_corpus)

        logger.info(f"索引构建完成: {len(chains)}条")

    def _extract_keywords(self, text: str) -> List[str]:
        """TF-IDF关键词提取"""
        import jieba
        import jieba.analyse

        return jieba.analyse.extract_tags(
            text,
            topK=20,
            withWeight=False,
            allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "an", "m", "q", "j"),
        )

    async def search(
        self, query: str, top_k: int = 5, recall_k: int = 10, use_bm25: bool = False
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Dense召回 + 可选 BM25 混合，返回 top_k 结果"""
        if not self.chains:
            return []

        query_emb = await self.embedding_model_handle.encode.remote(query)
        k = min(recall_k, len(self.chains))
        sims, idxs = self.dense_index.search(query_emb, k)

        dense_candidates = {int(idx) for idx in idxs[0]}
        results = [
            (self.chains[int(idx)], float(sim))
            for sim, idx in zip(sims[0], idxs[0])
        ]

        if use_bm25:
            import jieba
            import jieba.analyse

            tokens = jieba.analyse.extract_tags(query, topK=5, withWeight=False)
            scores = self.sparse_index.get_scores(tokens)
            top_indices = scores.argsort()[-k:][::-1]
            sparse_candidates = {int(idx) for idx in top_indices}

            extra = sparse_candidates - dense_candidates
            for idx in extra:
                results.append((self.chains[idx], float(scores[idx])))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
