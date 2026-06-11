"""SearchIntentRequest.reject_reconfirm 强制为 False 的回归测试

上游仍会传 true（触发"重写+再识别"的额外大模型调用，拖慢 search），
字段保留以兼容上游入参，但 schema 层强制矫正为 False。
"""
from unittest.mock import AsyncMock

from ark_nav.core.services.knowledge_base import NullKnowledgeBase
from ark_nav.domains.shouxian.router_schemas import SearchIntentRequest
from ark_nav.domains.shouxian.services.shouxian_nav_service import ShouXianNavService


def test_reject_reconfirm_true_coerced_to_false():
    request = SearchIntentRequest(message="查保单", reject_reconfirm=True)

    assert request.reject_reconfirm is False


def test_reject_reconfirm_upstream_json_payload_still_parses():
    # 上游照旧传 true 不应报 422，仅取值被忽略
    request = SearchIntentRequest.model_validate(
        {"message": "查保单", "msg_id": "m1", "reject_reconfirm": True})

    assert request.reject_reconfirm is False


def test_reject_reconfirm_default_unchanged():
    request = SearchIntentRequest(message="查保单")

    assert request.reject_reconfirm is False


async def test_search_passes_false_to_classifier_even_when_upstream_sends_true():
    # Arrange：FAQ 永不命中（NullKnowledgeBase），分类器打桩记录入参
    svc = ShouXianNavService(
        shouxian_intent_agent=None,
        knowledge_base=NullKnowledgeBase(domain="shouxian"))
    classify = AsyncMock(return_value="寿险意图")
    svc.classify_service.shouxian_classify_intent = classify
    request = SearchIntentRequest(
        message="帮我看看身故受益人怎么改", msg_id="m-rr", reject_reconfirm=True)

    # Act
    result = await svc.search(request)

    # Assert：分类器收到的 reject_reconfirm 是 False（走单次调用链路）
    assert result["data"]["service_type"] == "life_insurance"
    assert classify.await_args.args[2] is False
