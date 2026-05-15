from dotenv import load_dotenv

load_dotenv()
import asyncio
import json
import os.path
from typing import List, Dict, Any
import faiss
from ray import serve
from pathlib import Path
from ark_nav.core.models import RAGModelDeployment
from ark_nav.core.services.rag_service import HybridRetriever
from ark_nav.core.services.xiezhi_http import _get_faq_page_data, _get_faq_table_data
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger("ark_nav_AgentPfmKb_Service")


class AgentPfmKbService:
    def __init__(self, rag_models_handle, domain, kg_id):
        self.retriever = HybridRetriever(rag_models_handle)
        self.data_dir = f"{os.getenv('FAISS_INDEX_DIR')}/{domain}"
        self.is_index_updated = False
        enable_local_kg = os.getenv("ENABLE_LOCAL_KG", "False").strip().lower() == "true"
        if enable_local_kg:
            asyncio.create_task(self.load_data(kg_id=kg_id))

    @print_execution_time
    async def load_data(self, kg_id, is_reload: bool = False):
        """异步从接口加载数据并构建向量数据库"""
        logger.info(f"智能体平台知识库服务加载数据，知识库ID为 [{kg_id}]")
        if not kg_id:
            raise ValueError("知识库ID为空，请检查配置")
        chains = await _get_faq_page_data(kg_id)
        chains_2 = await _get_faq_table_data(kg_id)
        combined = chains + chains_2
        await self.build_index(combined, is_reload)

    @print_execution_time
    async def build_index(self, chains: List[Dict[str, Any]], is_reload: bool):
        """构建索引"""
        if not chains:
            raise ValueError("数据为空")
        await self.retriever.build_index(chains)

        data_dir = Path(self.data_dir)
        data_dir.mkdir(exist_ok=True)
        if self.retriever.chains and self.retriever.dense_index:
            index_path = data_dir / "faiss_index"
            faiss.write_index(self.retriever.dense_index, str(index_path))
            data_path = data_dir / "data.json"
            with open(data_path, "w", encoding='utf-8') as f:
                json.dump(self.retriever.chains, f, indent=4)

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

    def load_index(self):
        """从文件中加载向量检索"""
        data_dir = Path(self.data_dir)
        index_path = data_dir / "faiss_index"
        chains_path = data_dir / "data.json"
        if not os.path.exists(index_path) or not os.path.exists(chains_path):
            raise ValueError(f"向量文件不存在: {index_path}，请检查")

        with open(chains_path, "r", encoding='utf-8') as f:
            chains = json.load(f)
        self.retriever.load_index(index_path, chains)
