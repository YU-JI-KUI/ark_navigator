"""知识库抽象层

设计目标：
1. 业务代码只调 KnowledgeBase 接口，不感知本地 FAISS / 远程 REST 的差异
2. 模式切换由 KBConfig.MODE 决定，业务运行时不再读环境变量
3. 返回值契约统一：FAQ -> Optional[str]，Table -> Optional[Dict]
"""
from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, List, Optional, Protocol

from ark_nav.core.services.faiss_index_store import FaissIndexStore
from ark_nav.core.services.agent_platform_client import fetch_rag
from ark_nav.core.utils.kb_config import KBConfig
from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger(__name__)


class KnowledgeBase(Protocol):
    """知识库接口

    实现方需提供 FAQ / Table 两类语义化检索方法，以及 reload() 用于刷新索引。
    """

    domain: str
    kg_id: Optional[str]  # 业务知识库 ID（远程平台上的 knId），便于日志区分

    async def fetch_faq_answer(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        score_threshold: float = 0.9,
    ) -> Optional[str]:
        """检索 FAQ 答案文本，未命中返回 None"""
        ...

    async def fetch_table_knowledge(
        self,
        query: str,
        score_threshold: float = 0.85,
    ) -> Optional[Dict[str, Any]]:
        """检索 Table 类知识（结构化记录），未命中返回 None"""
        ...

    async def reload(self, faq_category_id: Optional[str] = None) -> None:
        """刷新底层索引。

        Args:
            faq_category_id:
              - None / 空字符串: 全量同步——重新拉取所有 FAQ + 所有 Table 并整体替换索引
              - 非空字符串（如 "12345"）：增量同步——只拉取该目录下的 FAQ，
                替换本地这个目录的 FAQ 条目；其他目录的 FAQ 和所有 Table 保持不变

        远程实现可为 no-op。
        """
        ...


class LocalFaissKnowledgeBase:
    """基于本地 FAISS 索引的实现，组合 FaissIndexStore 做实际存储/检索"""

    def __init__(self, embedding_model_handle, domain: str, kg_id: str):
        if not kg_id:
            raise ValueError(f"LocalFaissKnowledgeBase[{domain}] 需要 kg_id 才能从远程拉取初始数据")
        self.domain = domain
        self.kg_id = kg_id   # 公开属性，便于日志和外部读取
        self._inner = FaissIndexStore(embedding_model_handle=embedding_model_handle, domain=domain, kg_id=kg_id)

    async def fetch_faq_answer(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        score_threshold: float = 0.9,
    ) -> Optional[str]:
        results = await self._inner.search(
            query=query,
            score_threshold=score_threshold,
            top_k=1,
            kb_type="faq",
            kb_labels=labels,
        )
        if not results:
            return None
        return results[0].get("answer")

    async def fetch_table_knowledge(
        self,
        query: str,
        score_threshold: float = 0.85,
    ) -> Optional[Dict[str, Any]]:
        results = await self._inner.search(
            query=query,
            score_threshold=score_threshold,
            top_k=1,
            kb_type="table",
        )
        if not results:
            return None
        # 与远程实现的字段保持一致：table 模式下 sub_category_i 取自 text
        record = copy.copy(results[0])
        record["sub_category_i"] = record.get("text")
        return record

    async def reload(self, faq_category_id: Optional[str] = None) -> None:
        mode = "full" if not faq_category_id else f"partial(category_id={faq_category_id})"
        logger.info(f"LocalFaissKnowledgeBase[{self.domain}] reload start kg_id={self.kg_id} mode={mode}")
        await self._inner.load_data(kg_id=self.kg_id, faq_category_id=faq_category_id)
        logger.info(f"LocalFaissKnowledgeBase[{self.domain}] reload done mode={mode}")


class NullKnowledgeBase:
    """空实现：KB_MODE=none 时使用。

    检索永不命中（立即返回 None），业务链路自然落到大模型分类，
    实现"search 直连大模型"而不需要 service 层感知模式差异。
    reload 为 no-op，启动无需拉数据，同步调度器照常驱动也无副作用。
    """

    def __init__(self, domain: str):
        self.domain = domain
        self.kg_id: Optional[str] = None

    async def fetch_faq_answer(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        score_threshold: float = 0.9,
    ) -> Optional[str]:
        return None

    async def fetch_table_knowledge(
        self,
        query: str,
        score_threshold: float = 0.85,
    ) -> Optional[Dict[str, Any]]:
        return None

    async def reload(self, faq_category_id: Optional[str] = None) -> None:
        return None


class RemoteRestKnowledgeBase:
    """基于智能体平台远程 REST 接口的实现"""

    def __init__(self, domain: str, kg_id: Optional[str] = None):
        self.domain = domain
        self.kg_id = kg_id   # 公开属性，与 LocalFaissKnowledgeBase 一致

    async def fetch_faq_answer(
        self,
        query: str,
        labels: Optional[List[str]] = None,
        score_threshold: float = 0.9,
    ) -> Optional[str]:
        kb_ids = [self.kg_id] if self.kg_id else None
        result = await fetch_rag(
            query=query,
            kb_type=["faq"],
            kb_ids=kb_ids,
            labels=labels,
            score_threshold=score_threshold,
        )
        # fetch_rag 在 faq 分支返回 Optional[str]
        if result is None or isinstance(result, str):
            return result
        # 极端情况下返回了字典，兜底
        return result.get("answer") if isinstance(result, dict) else None

    async def fetch_table_knowledge(
        self,
        query: str,
        score_threshold: float = 0.85,
    ) -> Optional[Dict[str, Any]]:
        result = await fetch_rag(
            query=query,
            kb_type=["table"],
            score_threshold=score_threshold,
        )
        return result if isinstance(result, dict) else None

    async def reload(self, faq_category_id: Optional[str] = None) -> None:
        # 远程模式无本地索引可刷新；参数仅为接口兼容
        return None


def build_knowledge_base(
    embedding_model_handle,
    domain: str,
    kg_id: Optional[str],
    mode: Optional[str] = None,
) -> KnowledgeBase:
    """构造 KnowledgeBase 实例，支持 deployment 级别独立控制模式。

    Args:
        embedding_model_handle: Ray EmbeddingModelDeployment handle；仅 LOCAL 模式使用，REMOTE 模式可传 None
        domain: 业务域名，用于隔离索引目录与日志标记
        kg_id: 智能体平台知识库 ID；LOCAL 模式必填
        mode: 显式指定模式 "local" / "remote" / "none"（大小写不敏感）。
              传入则覆盖全局 KBConfig.MODE，用于 deployment 独立控制；
              传入无效值时打 warning 并回退到全局 KBConfig.MODE；
              传入 None 则走全局 KBConfig.MODE。
              "none" = 跳过知识库检索（永不命中），业务直连大模型。

    优先级链：传入 mode > KBConfig.MODE > 代码默认（"remote"）。
    """
    # 解析有效模式：传入优先，无效值/None 回退到全局
    candidate = (mode or "").strip().lower() if mode is not None else ""
    if mode is not None and candidate not in ("local", "remote", "none"):
        logger.warning(
            f"build_knowledge_base[{domain}] 收到无效 mode={mode!r}，"
            f"回退到 KBConfig.MODE={KBConfig.MODE}"
        )
        candidate = ""
    effective_mode = candidate or KBConfig.MODE.lower()
    source = "param" if candidate else "global"

    if effective_mode == "none":
        logger.info(f"build_knowledge_base domain={domain} mode=none mode_source={source} 检索跳过，直连大模型")
        return NullKnowledgeBase(domain=domain)
    if effective_mode == "local":
        if embedding_model_handle is None:
            raise ValueError(f"LOCAL 模式下 build_knowledge_base[{domain}] 需要 embedding_model_handle")
        logger.info(f"build_knowledge_base domain={domain} mode=local mode_source={source}")
        return LocalFaissKnowledgeBase(embedding_model_handle=embedding_model_handle, domain=domain, kg_id=kg_id or "")
    logger.info(f"build_knowledge_base domain={domain} mode=remote mode_source={source}")
    return RemoteRestKnowledgeBase(domain=domain, kg_id=kg_id)


def bootstrap_knowledge_base(knowledge_base: KnowledgeBase) -> None:
    """在 Ray Deployment 同步 __init__ 中阻塞等待索引就绪。

    实测 Ray Serve 的 Deployment __init__ 在 actor 的 event loop 线程中被调用，
    `asyncio.get_running_loop()` 总是返回非 None，因此必须用独立线程跑 asyncio.run
    才能真正阻塞等完，否则副本会带着空索引上线。

    - LOCAL 模式：拉取远程数据 → 构建 FAISS 索引；启动时间会增加几十秒到几分钟
    - REMOTE 模式：reload 是 no-op，本调用迅速返回
    - 失败 fail-fast：抛出异常，让 Ray 决定是否重启该副本
    """
    import threading

    logger.info(f"bootstrap_knowledge_base start domain={knowledge_base.domain}")

    def _run_in_new_loop():
        # 在新线程里用全新 event loop 跑 reload，与 Ray 自身的 loop 隔离
        asyncio.run(knowledge_base.reload())

    exception_box: list[BaseException] = []

    def runner():
        try:
            _run_in_new_loop()
        except BaseException as e:
            exception_box.append(e)

    try:
        # 不管当前线程有没有 event loop，统一走新线程模式，行为可预测
        worker = threading.Thread(target=runner, name=f"kb-bootstrap-{knowledge_base.domain}", daemon=True)
        worker.start()
        worker.join()  # 主线程阻塞等完
        if exception_box:
            raise exception_box[0]
    except Exception:
        logger.exception(f"bootstrap_knowledge_base failed domain={knowledge_base.domain}")
        raise
    finally:
        # 关键：bootstrap 在独立线程的临时 event loop 上调过 httpx，
        # httpx 的连接池绑定到了该 loop。线程退出 → loop 关闭 → client 实际已死。
        # 必须清空单例，让后续在 actor event loop 上调用 get_client() 时重建。
        # 否则 reconfigure 触发的首次 partial reload 会立即报 'Event loop is closed'。
        from ark_nav.core.utils.http_client_manager import reset_client_singleton
        reset_client_singleton()
    logger.info(f"bootstrap_knowledge_base done domain={knowledge_base.domain}")
