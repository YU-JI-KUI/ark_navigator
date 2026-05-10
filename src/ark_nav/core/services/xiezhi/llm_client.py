"""平安大模型 API 调用客户端。

从 xiezhi_http.py 拆分而来（2026-05），保持原函数签名与逻辑一字不改。

包含：
- call_bigmodel_api：唯一公开入口，支持指数退避重试与双签名认证
"""
import time
import uuid
from typing import Optional, Dict, Any

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
        **kwargs
) -> Optional[Dict[Any, Any]]:
    """
    调用 Qwen3 服务接口，发送 prompt 请求。

    :param url: API 接口地址
    :param prompt: 输入提示文本
    :param scene_id: 业务场景 ID（如 'customer_service', 'product_query' 等）
    :param app_key: 应用密钥
    :param app_secret: 应用密钥密钥（用于签名）
    :param timeout: 请求超时时间（秒）
    :param max_retries: 最大重试次数
    :return: API 响应 JSON，失败返回 None
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
        "gpt_signature": gpt_signature
    }
    request_id = str(uuid.uuid4())
    if isinstance(query, list):
        messages = query
    else:
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]
    payload = {
        "request_id": request_id,
        "messages": messages,
        "stream": False,
        "scene_id": scene_id,
        "seed": 42,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
        **kwargs
    }
    logger.info(f"Calling large model with {request_id}, scene_id-{scene_id}")
    for attempt in range(max_retries):
        try:
            try:
                response = await get_client().post(url=LLMPlfConfig.OPEN_AI_URL, headers=headers, json=payload,
                                                   timeout=timeout)
                logger.info(f"{request_id} 返回的response:{response.json()}")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"API call failed: {e}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return {"error": str(e)}

        except httpx.RequestError as e:
            logger.error(f"[WARNING] Request attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1 * (2 ** attempt))  # 指数退避
            else:
                return None

    return None
