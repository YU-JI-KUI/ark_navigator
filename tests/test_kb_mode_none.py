"""KB_MODE=none（跳过知识库检索，直连大模型）的单元测试

新增第三种知识库模式：NullKnowledgeBase 检索永不命中，
业务链路自然落到大模型分类，service 层无需感知模式差异。
"""
import uuid
from unittest.mock import AsyncMock

import pytest

from ark_nav.core.services.knowledge_base import (
    NullKnowledgeBase,
    build_knowledge_base,
)
from ark_nav.core.utils.kb_config import KBConfig
from ark_nav.domains.shouxian.router_schemas import SearchIntentRequest
from ark_nav.domains.shouxian.services.shouxian_nav_service import ShouXianNavService


def test_build_knowledge_base_mode_none_needs_no_handle_and_kg_id():
    # none 模式不依赖 embedding handle 和 kg_id，启动零成本
    kb = build_knowledge_base(
        embedding_model_handle=None, domain="shouxian", kg_id=None, mode="none")

    assert isinstance(kb, NullKnowledgeBase)
    assert kb.domain == "shouxian"


def test_build_knowledge_base_global_mode_none(monkeypatch):
    # 不传 deployment 级 mode 时，走全局 KB_MODE=none
    monkeypatch.setattr(KBConfig, "MODE", "none")

    kb = build_knowledge_base(
        embedding_model_handle=None, domain="shouxian", kg_id="123", mode=None)

    assert isinstance(kb, NullKnowledgeBase)


async def test_null_knowledge_base_never_hits():
    kb = NullKnowledgeBase(domain="shouxian")

    assert await kb.fetch_faq_answer(query="如何查保单") is None
    assert await kb.fetch_table_knowledge(query="安鑫保") is None
    assert await kb.reload() is None  # 同步调度器照常驱动也无副作用


def test_kb_config_accepts_none(monkeypatch):
    monkeypatch.setattr(KBConfig, "MODE", "none")

    KBConfig.check_required()  # 不应抛异常


def test_kb_config_rejects_invalid_mode(monkeypatch):
    monkeypatch.setattr(KBConfig, "MODE", "disabled")

    with pytest.raises(ValueError, match="KB_MODE"):
        KBConfig.check_required()


async def test_search_goes_straight_to_model_with_null_kb():
    # Arrange：真实 RagService + NullKnowledgeBase，只 mock 大模型分类
    svc = ShouXianNavService(
        shouxian_intent_agent=None,
        knowledge_base=NullKnowledgeBase(domain="shouxian"))
    model = AsyncMock(return_value="寿险意图")
    svc.classify_service.shouxian_classify_intent = model

    # Act：uuid 保证消息唯一，避开进程级 FAQ 缓存
    request = SearchIntentRequest(message=f"查保单{uuid.uuid4().hex}", msg_id="m1")
    result = await svc.search(request)

    # Assert：FAQ 永不命中，结果来自大模型
    assert result == {"code": "success", "data": {"service_type": "life_insurance"}}
    model.assert_awaited_once()
