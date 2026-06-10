"""search 接口降延迟改造的单元测试

覆盖四个点：
1. P0 — FAQ 检索与大模型分类并行，FAQ 命中时短路并取消大模型任务
2. P1 — 意图分类调用透传 max_tokens 限制输出长度
3. P2 — 大模型客户端网络错误走 asyncio.sleep 指数退避（不阻塞 event loop）
4. P3 — 缓存 key 归一化，标点/空白变体共享缓存
"""
import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ark_nav.domains.shouxian.router_schemas import SearchIntentRequest
from ark_nav.domains.shouxian.services.shouxian_nav_service import (
    RagService,
    ShouXianNavService,
    _normalize_cache_key,
)
from ark_nav.domains.shouxian.intent_classifier_simple import classify_user_intent
from ark_nav.core.services.llm_platform_client import call_bigmodel_api


def _make_service(rag_result, model_result="寿险意图", rag_delay=0.0, model_delay=0.0):
    """构造 service 并 mock 掉两个边界依赖（FAQ 检索 / 大模型分类）"""
    svc = ShouXianNavService(shouxian_intent_agent=None, knowledge_base=None)
    flags = {"model_started": False, "model_cancelled": False}

    async def fake_rag(msg_id, message):
        await asyncio.sleep(rag_delay)
        return rag_result

    async def fake_model(msg_id, message, reject_reconfirm, history):
        flags["model_started"] = True
        try:
            await asyncio.sleep(model_delay)
        except asyncio.CancelledError:
            flags["model_cancelled"] = True
            raise
        return model_result

    svc.rag_service.fetch_rag = fake_rag
    svc.classify_service.shouxian_classify_intent = fake_model
    return svc, flags


# ---------------------------------------------------------------------------
# P0 — 并行 + 短路
# ---------------------------------------------------------------------------


async def test_search_faq_hit_short_circuits_and_cancels_model():
    # Arrange：FAQ 直接命中寿险意图，大模型任务故意拖 5 秒
    svc, flags = _make_service(rag_result="寿险意图", model_delay=5.0)

    # Act
    start = time.monotonic()
    result = await svc.search(SearchIntentRequest(message="查保单", msg_id="m1"))
    elapsed = time.monotonic() - start
    await asyncio.sleep(0.01)  # 给取消一个调度周期

    # Assert：立即返回、不等大模型，且任务被取消
    assert result == {"code": "success", "data": {"service_type": "life_insurance"}}
    assert elapsed < 1.0
    assert flags["model_cancelled"] is True


async def test_search_faq_rejection_short_circuits():
    # Arrange
    svc, _ = _make_service(rag_result="拒识")

    # Act
    result = await svc.search(SearchIntentRequest(message="今天天气", msg_id="m2"))

    # Assert
    assert result["data"]["service_type"] == "rejection"


async def test_search_faq_miss_falls_back_to_model():
    # Arrange：FAQ 不命中，模型判拒识
    svc, flags = _make_service(rag_result="", model_result="拒识")

    # Act
    result = await svc.search(SearchIntentRequest(message="如何减肥", msg_id="m3"))

    # Assert
    assert result["data"]["service_type"] == "rejection"
    assert flags["model_started"] is True


async def test_search_rag_and_model_run_in_parallel():
    # Arrange：检索和模型各 0.2s，串行要 0.4s+，并行应接近 0.2s
    svc, _ = _make_service(rag_result="", model_result="寿险意图",
                           rag_delay=0.2, model_delay=0.2)

    # Act
    start = time.monotonic()
    result = await svc.search(SearchIntentRequest(message="买保险", msg_id="m4"))
    elapsed = time.monotonic() - start

    # Assert
    assert result["data"]["service_type"] == "life_insurance"
    assert elapsed < 0.35, f"并行执行应耗时约 0.2s，实际 {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# P3 — 缓存 key 归一化
# ---------------------------------------------------------------------------


def test_normalize_cache_key_strips_punct_and_whitespace():
    assert _normalize_cache_key("转人工。") == "转人工"
    assert _normalize_cache_key(" 转人工 ") == "转人工"
    assert _normalize_cache_key("转人工！！") == "转人工"
    assert _normalize_cache_key("查  保单") == "查 保单"


def test_normalize_cache_key_pure_punct_falls_back_to_original():
    # 纯标点输入不能归一化成空串，否则不同输入会互相串缓存
    assert _normalize_cache_key("。。。") == "。。。"


async def test_fetch_faq_cache_hits_across_punctuation_variants():
    # Arrange：uuid 保证消息全局唯一，避免进程级缓存被其他测试污染
    base = f"帮我查保单{uuid.uuid4().hex}"
    kb = MagicMock()
    kb.fetch_faq_answer = AsyncMock(return_value="寿险意图")
    rag = RagService(kb)

    # Act：同一意图的三种标点/空白变体
    r1 = await rag.fetch_rag(msg_id="a", message=base)
    r2 = await rag.fetch_rag(msg_id="b", message=f" {base}。")
    r3 = await rag.fetch_rag(msg_id="c", message=f"{base}！")

    # Assert：只回源一次，后两次命中缓存
    assert r1 == r2 == r3 == "寿险意图"
    assert kb.fetch_faq_answer.await_count == 1


# ---------------------------------------------------------------------------
# P1 — max_tokens 透传
# ---------------------------------------------------------------------------


async def test_classify_user_intent_passes_max_tokens(monkeypatch):
    # Arrange
    monkeypatch.setenv("SCENE_ID", "test-scene")
    api_mock = AsyncMock(return_value={"choices": [{"message": {"content": "寿险意图"}}]})

    # Act
    with patch("ark_nav.domains.shouxian.intent_classifier_simple.call_bigmodel_api", api_mock):
        result = await classify_user_intent(app_key="k", app_secret="s", user_message="查保单")

    # Assert
    assert result == "寿险意图"
    assert api_mock.await_args.kwargs["max_tokens"] == 10


# ---------------------------------------------------------------------------
# P2 — 网络错误异步退避重试
# ---------------------------------------------------------------------------


async def test_call_bigmodel_api_retries_network_error_with_async_backoff():
    # Arrange：第一次连接失败，第二次成功
    ok_response = MagicMock()
    ok_response.json.return_value = {"ok": True}
    ok_response.raise_for_status.return_value = None
    client = MagicMock()
    client.post = AsyncMock(side_effect=[httpx.ConnectError("boom"), ok_response])
    sleep_mock = AsyncMock()

    # Act
    with patch("ark_nav.core.services.llm_platform_client.get_client", return_value=client), \
         patch("ark_nav.core.services.llm_platform_client.get_sign", return_value="sig"), \
         patch("ark_nav.core.services.llm_platform_client.generate_app_sign", return_value="sig"), \
         patch("ark_nav.core.services.llm_platform_client.asyncio.sleep", sleep_mock):
        result = await call_bigmodel_api(query="q", scene_id="s", app_key="k", app_secret="s")

    # Assert：重试成功，退避走的是 asyncio.sleep（首次退避 1s）
    assert result == {"ok": True}
    assert client.post.await_count == 2
    sleep_mock.assert_awaited_once_with(1)
