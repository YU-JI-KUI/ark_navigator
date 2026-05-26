import asyncio
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np

from ark_nav.core.utils.nav_logger import get_logger, remote_with_trace

logger = get_logger(__name__)


def _build_faiss_index_sync(embeddings: np.ndarray) -> faiss.Index:
    """同步构建 FAISS 索引。被 asyncio.to_thread 调起，跑在工作线程而非 event loop 上。"""
    arr = embeddings.astype("float32")
    index = faiss.IndexFlatIP(arr.shape[1])
    index.add(arr)
    return index


class DenseRetriever:
    """基于 FAISS 的稠密向量检索器，含 embedding 缓存。

    缓存策略：
    - cache key 是 chain 的 text（FAQ 问题文本）
    - cache value 是 1D embedding 向量
    - 同一 text 的 embedding 永远相同（embedding 只看 text，不看 answer / 其他字段）
    - 全量同步前 clear_cache=True 主动清空，作为防御性兜底
    - 增量同步保留 cache，命中率高时 GPU 计算量从 N 降到只算新增条目
    - embedding 模型升级（dimension 变化）→ 自动清空
    """

    def __init__(self, embedding_model_handle):
        self.embedding_model_handle = embedding_model_handle
        self.dense_index: Optional[faiss.Index] = None
        self.chains: List[Dict[str, Any]] = []
        # text → embedding (1D ndarray)
        self._embedding_cache: Dict[str, np.ndarray] = {}
        # 记录 cache 里 embedding 的维度，模型升级时检测
        self._cached_dim: Optional[int] = None

    async def build_index(self, chains: List[Dict[str, Any]], clear_cache: bool = False):
        """构建向量索引（双缓冲 + embedding cache 复用）

        Args:
            chains: 完整的 chain 列表
            clear_cache: True 时先清空 embedding cache（全量同步建议传 True 做防御性兜底；
                        增量同步传 False 享受 cache 复用加速）

        关键优化：
        - 已缓存的 text 直接复用 embedding，跳过 GPU 计算
        - 只对新 text 调 batch_encode（GPU 工作量从 len(chains) 降到 len(new_texts)）
        - 构建后清理 cache 中不在新 chains 里的旧 text（防止内存无限增长）
        """
        texts = [c.get("text", "") for c in chains]

        if clear_cache:
            logger.info(
                f"DenseRetriever 清空 embedding cache, "
                f"old_size={len(self._embedding_cache)} reason=clear_cache=True"
            )
            self._embedding_cache.clear()
            self._cached_dim = None

        # 分离：已缓存（按当前 chains 顺序的位置）vs 需新算
        cached_positions: List[int] = []
        new_positions: List[int] = []
        new_texts: List[str] = []
        for i, t in enumerate(texts):
            if t in self._embedding_cache:
                cached_positions.append(i)
            else:
                new_positions.append(i)
                new_texts.append(t)

        logger.info(
            f"DenseRetriever build_index 复用={len(cached_positions)} 新算={len(new_texts)} "
            f"total={len(texts)} cache_hit_rate={(len(cached_positions) / max(len(texts), 1)) * 100:.1f}%"
        )

        # 只对新 text 调 GPU
        if new_texts:
            new_embeddings = await remote_with_trace(
                self.embedding_model_handle.batch_encode,
                new_texts,
                batch_size=32,
                show_progress_bar=True,
                normalize_embeddings=True,
            )
            new_embeddings = np.asarray(new_embeddings).astype("float32")
            new_dim = new_embeddings.shape[1]

            # 检测 embedding dimension 变化（模型升级场景）
            if self._cached_dim is not None and self._cached_dim != new_dim:
                # 旧 cache 维度不匹配，全部失效；本次必须重算所有 chain
                logger.warning(
                    f"DenseRetriever embedding dimension 变化 "
                    f"old={self._cached_dim} new={new_dim}，清空 cache 并重算全部 chain"
                )
                self._embedding_cache.clear()
                self._cached_dim = new_dim
                # 重新对全部 texts 调 GPU（之前只算了 new_texts，旧的复用失效了）
                logger.info(f"DenseRetriever 重算全部 {len(texts)} 条 chain")
                full_new = await remote_with_trace(
                    self.embedding_model_handle.batch_encode,
                    texts,
                    batch_size=32,
                    show_progress_bar=True,
                    normalize_embeddings=True,
                )
                full_new = np.asarray(full_new).astype("float32")
                for j, t in enumerate(texts):
                    self._embedding_cache[t] = full_new[j]
            else:
                # 正常路径：维度一致，把新算的写入 cache
                self._cached_dim = new_dim
                for j, t in enumerate(new_texts):
                    self._embedding_cache[t] = new_embeddings[j]

        # 拼装完整 embeddings 数组（顺序对齐 chains）
        if self._cached_dim is None:
            # 极端场景：chains 为空 或 cache 为空且 new_texts 为空
            raise ValueError("DenseRetriever build_index 无法确定 embedding 维度")
        full_embeddings = np.zeros((len(texts), self._cached_dim), dtype="float32")
        for i, t in enumerate(texts):
            full_embeddings[i] = self._embedding_cache[t]

        new_dense_index = await asyncio.to_thread(_build_faiss_index_sync, full_embeddings)

        # 清理 cache 中已不在新 chains 里的旧 text，防止内存无限增长
        new_text_set = set(texts)
        old_size = len(self._embedding_cache)
        self._embedding_cache = {
            t: e for t, e in self._embedding_cache.items() if t in new_text_set
        }
        purged = old_size - len(self._embedding_cache)
        if purged > 0:
            logger.info(f"DenseRetriever cache 清理 purged={purged} 当前 size={len(self._embedding_cache)}")

        # 原子替换两个字段
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
