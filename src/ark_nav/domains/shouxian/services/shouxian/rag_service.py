"""寿险 RAG 服务（本地 KG / 远程 RAG 二选一）。

从 shouxian_nav_service.py 拆分而来（2026-05），保持原 class 行为一字不改。

负责：
- 根据 ENABLE_LOCAL_KG 环境变量切换检索路径
- 缓存层：aiocache 600s TTL，namespace=shouxian, noself=True（实例间共享）

⚠️ 注意：与本目录的"rag_service"模块名相同的类位于 domains/shouxian/services/shouxian_rag_service.py，
不是同一个东西。前者是基于 FAISS+HybridRetriever 的本地检索器，
此处的 RagService 只是对其与远端 fetch_rag 的薄封装。
"""
import os

from aiocache import cached
from aiocache.serializers import StringSerializer

from ark_nav.core.services.xiezhi_http import fetch_rag
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


class RagService:

    def __init__(self, agent_pfm_kb_svc):
        self.agent_pfm_kb_svc = agent_pfm_kb_svc

    @print_execution_time
    async def fetch_rag(self, msg_id: str, message: str):
        rag_answer = await self._fetch_rag_remote(message=message)
        rag_answer = rag_answer if rag_answer else ""
        logger.info(f'msg_id = {msg_id} message = {message} 知识库返回结果 = {rag_answer}')
        return rag_answer

    @cached(ttl=600, namespace="shouxian", serializer=StringSerializer(), noself=True)
    async def _fetch_rag_remote(self, message: str):
        enable_local_kg = os.getenv("ENABLE_LOCAL_KG", "False").strip().lower() == "true"
        if enable_local_kg:
            logger.info("query from local knowledge base")
            data = await self.agent_pfm_kb_svc.search(query=message, score_threshold=0.9, top_k=1, kb_type="faq",
                                                       use_rerank=False)
            rag_answer = data[0].get("answer") if len(data) >= 1 else None
            return rag_answer
        else:
            logger.info("query from remote knowledge base")
            rag_answer = await fetch_rag(query=message, kb_type=["faq"], kb_ids=[os.getenv("SHOUXIAN_AGENT_PLATFORM_KG_ID")])
            return rag_answer
