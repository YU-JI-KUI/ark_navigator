from dotenv import load_dotenv

load_dotenv()
from typing import List, Dict, Any

from ark_nav.core.services.hybrid_retriever import HybridRetriever
from ark_nav.core.services.xiezhi_http import _get_faq_page_data, _get_faq_table_data
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


class FaissIndexStore:
    """基于 FAISS 的本地向量索引存储与检索。

    职责：
    1. 从远程数据源拉取 FAQ + Table 数据
    2. 委托 HybridRetriever 构建内存中的向量索引
    3. 提供带过滤条件（kb_type / labels / score_threshold）的检索接口

    索引仅在内存中维护，不落盘；进程重启后由上层 LocalFaissKnowledgeBase 重新加载。
    """

    def __init__(self, embedding_model_handle, domain, kg_id):
        self.retriever = HybridRetriever(embedding_model_handle)
        self.domain = domain
        self.is_index_updated = False
        self._initial_kg_id = kg_id
        # 索引加载交由上层 LocalFaissKnowledgeBase 显式驱动

    @print_execution_time
    async def load_data(self, kg_id, is_reload: bool = False):
        """从远程接口加载数据并构建向量索引"""
        logger.info(f"FaissIndexStore[{self.domain}] 加载数据 kg_id={kg_id}")
        if not kg_id:
            raise ValueError("知识库ID为空，请检查配置")
        chains = await _get_faq_page_data(kg_id)
        chains_2 = await _get_faq_table_data(kg_id)
        combined = chains + chains_2
        await self.build_index(combined, is_reload)

    @print_execution_time
    async def build_index(self, chains: List[Dict[str, Any]], is_reload: bool):
        """构建内存中的向量索引（不落盘）"""
        if not chains:
            raise ValueError("数据为空")
        await self.retriever.build_index(chains)
        self.is_index_updated = is_reload

    @print_execution_time
    async def search(self, query: str, top_k: int = 5, score_threshold: float = 0.9,
                     kb_type: str = "faq", kb_labels: List[str] = None) -> List[Dict[str, Any]]:
        """异步向量检索"""

        data = await self.retriever.search(query, top_k=20, recall_k=20)
        results = []
        for item in data:
            score = item[1]
            type = item[0].get("kbType")
            labels = item[0].get("kbLabel", "").split("#")

            if score < score_threshold:
                continue

            if type != kb_type:
                continue

            if kb_labels and not any(label in labels for label in kb_labels):
                continue

            results.append(item[0])
        return results[:top_k]
