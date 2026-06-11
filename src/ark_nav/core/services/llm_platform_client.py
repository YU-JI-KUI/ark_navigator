"""平安大模型平台（Qwen3 等）API 客户端。

只负责调用平安大模型 OPEN AI 接口。和"智能体平台"（FAQ / RAG）完全独立，
两者鉴权方式、URL、签名机制都不同，不应该混在同一个模块里。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from ark_nav.core.services.gpt_signature import generate_app_sign
from ark_nav.core.services.open_ai_signature import get_sign
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.llm_platform_config import LLMPlfConfig
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


@print_execution_time
async def call_bigmodel_api(
        query: str | list,
        scene_id: str,
        app_key: str,
        app_secret: str,
        timeout: int = 6,
        max_retries: int = 3,
        **kwargs,
) -> Optional[Dict[Any, Any]]:
    """调用平安大模型 Qwen3 服务接口。

    Args:
        query: 字符串（自动包成 user message）或完整 messages list
        scene_id: 业务场景 ID
        app_key: 应用 key（用于 GPT 签名）
        app_secret: 应用 secret（用于 GPT 签名）
        timeout: 单次请求超时（秒）
        max_retries: 最大重试次数
        **kwargs: 透传给 payload 的额外字段
    Returns:
        API 响应 JSON；调用失败返回 {"error": "..."} 或 None
    """
    request_timestamp = str(int(time.time() * 1000))
    open_ai_signature = get_sign(LLMPlfConfig.RSA_PK, request_timestamp)
    gpt_signature = generate_app_sign(app_key, app_secret, request_timestamp)

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "openApiCode": LLMPlfConfig.OPEN_API_CODE,
        "openApiCredential": LLMPlfConfig.CRE_ID,
        "openApiRequestTime": request_timestamp,
        "openApiSignature": open_ai_signature,
        "gpt_app_key": app_key,
        "gpt_signature": gpt_signature,
    }
    request_id = str(uuid.uuid4())
    if isinstance(query, list):
        messages = query
    else:
        messages = [{"role": "user", "content": query}]
    payload = {
        "request_id": request_id,
        "messages": messages,
        "stream": False,
        "scene_id": scene_id,
        "seed": 42,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
        **kwargs,
    }
    logger.info(f"Calling large model with {request_id}, scene_id={scene_id}")
    for attempt in range(max_retries):
        try:
            try:
                response = await get_client().post(
                    url=LLMPlfConfig.OPEN_AI_URL,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                logger.info(f"{request_id} 返回的response:{response.json()}")
                response.raise_for_status()
                return response.json()
            except httpx.RequestError:
                # 网络层错误交给外层做指数退避重试；
                # 此前被下面的 except Exception 吞掉，外层退避分支实际是死代码
                raise
            except Exception as e:
                logger.error(f"API call failed: {e}")
                if attempt < max_retries - 1:
                    continue
                return {"error": str(e)}
        except httpx.RequestError as e:
            logger.error(f"[WARNING] Request attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                # 必须用 asyncio.sleep：time.sleep 会卡住整个 event loop，
                # 同副本上所有并发请求都会跟着停摆
                await asyncio.sleep(1 * (2 ** attempt))
            else:
                return None

    return None
