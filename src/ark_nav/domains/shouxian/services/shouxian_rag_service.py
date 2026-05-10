"""FAISS向量检索服务"""

import json
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple
import pandas as pd
from ark_nav.config import settings
from ark_nav.core.services.rag_service import HybridRetriever, SimpleRuleEngine
from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger(__name__)


class ShouxianRAGService:
    """FAISS向量检索服务"""

    def __init__(
        self,
        rag_models_handle,
        dedup_threshold: float = 0.75,
        top_k: int = 5,
        recall_k: int = 10,
        high_sim_threshold: float = 0.95,
        rules_path: Optional[str] = None
    ):
        self.dedup_threshold = dedup_threshold
        self.top_k = top_k
        self.recall_k = recall_k
        self.high_sim_threshold = high_sim_threshold
        self.rule_engine = SimpleRuleEngine(rules_path)
        self.retriever = HybridRetriever(rag_models_handle)
        self.init_cot_rules()

    def init_cot_rules(self):
        index_path = Path(settings.faiss_index_path)
        if index_path.exists():
            chains = self.load_data("data/D_1229_cots_std.xlsx")
            chains_2 = self.load_data("data/1_菜单扩写_cot_std.xlsx")
            combined =  chains + chains_2
            logger.info("找到了COT的向量index，准备加载")
            self.retriever.load_index(index_path,combined)
        else:
            raise Exception("there is not COT index")
        # else:
        #     chains = self.load_data("data/D_1229_cots_std.xlsx")
        #     chains_2 = self.load_data("data/1_菜单扩写_cot_std.xlsx")
        #     combined =  chains + chains_2
        #     await self.build_index(combined)

    def _extract_text_for_dedup(self, chain: Dict[str, Any]) -> str:
        """提取用于向量化的文本"""
        return chain.get("cot_feedback") or chain.get("text", "")

    def _extract_text_for_search(self, chain: Dict[str, Any]) -> str:
        """提取用于向量化的文本"""
        return chain.get("text","")

    def load_data(self, path: str) -> List[Dict[str, Any]]:
        """加载数据"""
        logger.info(f"加载数据: {path}")
        file_path = Path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        ext = file_path.suffix.lower()

        if ext == '.xlsx':
            df = pd.read_excel(path, engine='openpyxl')
            df.columns = df.columns.str.strip()

            cols_map = {col.lower(): col for col in df.columns}
            required = ["text", "label", "cot_feedback"]
            missing = [c for c in required if c not in cols_map]
            if missing:
                raise ValueError(f"缺少列: {missing}")

            df = df[[cols_map[c] for c in required]]
            df.columns = required
            chains = df.to_dict('records')

            for chain in chains:
                for k in chain:
                    chain[k] = "" if pd.isna(chain[k]) else str(chain[k]).strip()

        elif ext == '.json':
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            chains = data if isinstance(data, list) else data.get("data", [])

        else:
            raise ValueError(f"不支持的格式: {ext}")

        chains = [c for c in chains if c.get("text", "").strip() and c.get("cot_feedback", "").strip()]
        logger.info(f"加载完成: {len(chains)}条")
        return chains

    async def build_index(self, chains: List[Dict[str, Any]]):
        """构建索引"""
        if not chains:
            raise ValueError("数据为空")
        await self.retriever.build_index(chains)

    async def search(self, query: str) -> List[Tuple[Dict[str, Any], float]]:
        """混合检索 + 规则过滤"""
        rule_label = self.rule_engine.predict(query)
        results = await self.retriever.search(query, top_k=self.top_k, recall_k=self.recall_k)

        # if rule_label:
        #     results = [(c, s) for c, s in results if c.get("label") == rule_label]

        return results[:self.top_k]
