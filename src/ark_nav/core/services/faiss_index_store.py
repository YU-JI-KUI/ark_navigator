from dotenv import load_dotenv

load_dotenv()
from typing import List, Dict, Any, Optional

from ark_nav.core.services.dense_retriever import DenseRetriever
from ark_nav.core.services.agent_platform_client import _get_faq_page_data, _get_faq_table_data
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


class FaissIndexStore:
    """基于 FAISS 的本地向量索引存储与检索。

    职责：
    1. 从远程数据源拉取 FAQ + Table 数据
    2. 委托 DenseRetriever 构建内存中的向量索引
    3. 提供带过滤条件（kb_type / labels / score_threshold）的检索接口

    支持两种同步模式：
    - 全量同步（faq_category_id=None）：重新拉取所有 FAQ + Table，整体替换
    - 增量同步（faq_category_id="12345"）：只拉指定目录的 FAQ，替换本地相应条目；
      Table 数据和其他目录的 FAQ 保持不变

    索引仅在内存中维护，不落盘；进程重启后由上层 LocalFaissKnowledgeBase 重新加载。
    """

    def __init__(self, embedding_model_handle, domain, kg_id):
        self.retriever = DenseRetriever(embedding_model_handle)
        self.domain = domain
        self.is_index_updated = False
        self._initial_kg_id = kg_id
        # 持有完整数据快照，支持增量同步时按 categoryId 局部替换
        self._all_chains: List[Dict[str, Any]] = []
        # 索引加载交由上层 LocalFaissKnowledgeBase 显式驱动

    @print_execution_time
    async def load_data(self, kg_id, faq_category_id: Optional[str] = None):
        """从远程接口加载数据并构建向量索引。

        Args:
            kg_id: 知识库 ID
            faq_category_id:
              - None / 空字符串: 全量同步——拉所有 FAQ + 所有 Table，整体替换 self._all_chains
              - 非空字符串：增量同步——只拉该目录下的 FAQ，替换本地这个目录的 FAQ；
                其他目录的 FAQ 和所有 Table 保持不变
        """
        if not kg_id:
            raise ValueError("知识库ID为空，请检查配置")

        if not faq_category_id:
            # 全量同步
            logger.info(f"FaissIndexStore[{self.domain}] 全量加载 kg_id={kg_id}")
            faq_chains = await _get_faq_page_data(kg_id)
            table_chains = await _get_faq_table_data(kg_id)
            new_chains = faq_chains + table_chains
            logger.info(
                f"FaissIndexStore[{self.domain}] 全量数据 faq={len(faq_chains)} "
                f"table={len(table_chains)} total={len(new_chains)}"
            )
        else:
            # 增量同步：只拉指定 categoryId 的 FAQ
            # 注意：远程 API 用 categoryId 过滤，但响应不返回 categoryId 字段；
            # 本地按 categoryName 匹配——从拉到的数据中提取 categoryName 集合作为删除键
            logger.info(f"FaissIndexStore[{self.domain}] 增量加载 kg_id={kg_id} category_id={faq_category_id}")
            partial_faq = await _get_faq_page_data(kg_id, category_id=faq_category_id)

            if not partial_faq:
                # 拉到空——可能 API 异常，也可能目录真的被清空。保守起见不动旧数据。
                # 如果运维真的清空了目录，等下次 21:30 全量同步修正
                logger.warning(
                    f"FaissIndexStore[{self.domain}] 增量拉到 0 条数据 "
                    f"category_id={faq_category_id}，保留旧数据不动"
                )
                return

            # 从拉到的数据中提取这个 categoryId 对应的所有 categoryName（通常只有 1 个）
            target_names = {c.get("categoryName", "") for c in partial_faq}
            target_names.discard("")

            kept = [
                c for c in self._all_chains
                if not self._is_faq_in_category_names(c, target_names)
            ]
            new_chains = kept + partial_faq
            logger.info(
                f"FaissIndexStore[{self.domain}] 增量数据 kept={len(kept)} "
                f"new_partial={len(partial_faq)} total={len(new_chains)} "
                f"matched_category_names={sorted(target_names)}"
            )

        self._all_chains = new_chains
        await self.build_index(new_chains, is_reload=True)

    @staticmethod
    def _is_faq_in_category_names(chain: Dict[str, Any], target_names: set) -> bool:
        """判断一条 chain 是否是 FAQ 类型且 categoryName 属于目标集合"""
        if not target_names:
            return False
        if chain.get("kbType") != "faq":
            return False
        return chain.get("categoryName", "") in target_names

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
