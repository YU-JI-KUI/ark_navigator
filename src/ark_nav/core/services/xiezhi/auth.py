"""智能体平台认证。

从 xiezhi_http.py 拆分而来（2026-05），保持原函数签名与逻辑一字不改。
"""
import httpx
import json

from ark_nav.core.utils.agent_platform_config import AgentPfmConfig
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


@print_execution_time
async def _get_agent_auth_token(client: httpx.AsyncClient) -> str | None:
    auth_url = f"{AgentPfmConfig.HOST}{AgentPfmConfig.TOKEN_URL}"

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }

    payload = {
        "appId": AgentPfmConfig.TENANT_ID,
        "appSecret": AgentPfmConfig.APP_SEC
    }

    logger.info(f"Calling agent model to get the auth token")
    try:
        logger.info(f"token_url:{auth_url}")
        response = await get_client().post(url=auth_url, headers=headers, json=payload, timeout=30)
        logger.info(f"succeed to get the auth token from agent platfrom")
        response.raise_for_status()
        response_json = response.json()
        if response_json.get("msg") == "success":
            return response_json.get("data")
        else:
            raise Exception(f"API call failed: {response_json.get('msg')}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {response}, error: {e}")
    except Exception as e:
        logger.error(f"API call failed: {e}", exc_info=True)
    return None
