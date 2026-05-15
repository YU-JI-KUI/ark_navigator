import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import faiss
from rank_bm25 import BM25Okapi


class HybridRetriever:
    """混合召回（Dense + BM25）"""

    def __init__(self, rag_models_handle):
        self.rag_models_handle = rag_models_handle
        self.dense_index: Optional[faiss.Index] = None
        self.sparse_index: Optional[BM25Okapi] = None
        self.chains: List[Dict[str, Any]] = []

    async def build_index(self, chains: List[Dict[str, Any]]):
        """构建双索引"""
        self.chains = chains
        texts = [c.get("text", "") for c in chains]

        print("构建Dense索引...")
        embeddings = await self.rag_models_handle.batch_encode.remote(
            texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True
        )
        self.dense_index = faiss.IndexFlatIP(embeddings.shape[1])
        self.dense_index.add(embeddings.astype("float32"))

        print("构建Sparse索引...")
        tokenized_corpus = [self._extract_keywords(text) for text in texts]
        self.sparse_index = BM25Okapi(tokenized_corpus)

        print(f"索引构建完成: {len(chains)}条")

    def load_index(self, index_path, chains):
        print("加载Dense索引...")
        self.chains = chains
        self.dense_index = faiss.read_index(str(index_path))
        print("Dense索引加载完毕...")

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

        query_emb = await self.rag_models_handle.encode.remote(query)
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


class SimpleRuleEngine:
    """规则引擎"""

    def __init__(self, rules_path: Optional[str] = None):
        if rules_path and Path(rules_path).exists():
            with open(rules_path, "r", encoding="utf-8") as f:
                rules = json.load(f)
        else:
            rules = self._default_rules()

        self.life_keywords = rules.get("life_keywords", [])
        self.exclude_keywords = rules.get("exclude_keywords", [])
        self.life_patterns = [re.compile(kw) for kw in self.life_keywords]
        self.exclude_patterns = [re.compile(kw) for kw in self.exclude_keywords]

    def _default_rules(self):
        return {
            "life_keywords": [
                "寿险", "人寿", "终身寿险", "定期寿险",
                "身故保险金", "受益人", "保单贷款", "现金价值",
                "生存金", "分红", "万能险",
            ],
            "exclude_keywords": [
                "车险", "汽车保险", "交强险", "车损", "三者险",
                "财产险", "家财险", "盗抢险",
            ],
        }

    def predict(self, text: str) -> Optional[str]:
        """规则预判"""
        text = text.lower()
        for pattern in self.exclude_patterns:
            if pattern.search(text):
                return "非寿险"
        for pattern in self.life_patterns:
            if pattern.search(text):
                return "寿险"
        return None
