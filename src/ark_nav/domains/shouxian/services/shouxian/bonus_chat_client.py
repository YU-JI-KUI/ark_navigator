"""寿险中控（红利渠道）HTTP 客户端。

从 shouxian_nav_service.py 拆分而来（2026-05），保持原 class 行为一字不改。
2026-05 命名规范整改：原类名 BonusChatAgent，但实际是普通 HTTP 客户端
（不是 LLM agent），重命名为 BonusChatClient，旧名作为 alias 保留至下次 release。

负责：
- ESG OAuth access_token 的获取与 30 天 TTL 缓存（实例属性）
- 调用寿险中控 submit_business_request 接口（含 token 失效自动重试一次）

注意：每个 IntentRecognitionService 实例化时都会 new 一个 BonusChatClient，
故 token 缓存以"实例"为粒度（详见 docs/MODULE_MAP.md 阶段 5 风险点 1）。
"""
import datetime
import os
from typing import Any, Dict

from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


class BonusChatClient:

    def __init__(self):
        self.token = None
        self.token_expiry = datetime.datetime.now()
        self.bonus_chat_addr = os.getenv("ESG_BONUS_CHAT_ADDR")

    async def get_access_token(self, force=False):
        # access_token需要30天内失效

        async def _get_access_token():
            """获取 access token"""
            oauth_url = os.getenv("ESG_OAUTH_URL")
            client_id = os.getenv("ESG_CLIENT_ID_4_BONUS")
            grant_type = os.getenv("ESG_GRANT_TYPE_4_BONUS")
            client_secret = os.getenv("ESG_CLIENT_SECRET_4_BONUS")
            url = f"{oauth_url}?client_id={client_id}&grant_type={grant_type}&client_secret={client_secret}"
            try:
                response = await get_client().get(url)
                result = response.json()
                ret = result.get("ret")

                if ret != "0":
                    msg = result.get("msg", "未知错误")
                    raise Exception(f"获取token失败: {msg}")

                token = result["data"]["access_token"]
                if self.token is None or self.token != token:
                    self.token_expiry = datetime.datetime.now() + datetime.timedelta(days=int(os.getenv("ESG_TOKEN_EXPIRY")))
                    self.token = token

            except Exception as e:
                raise Exception(f"获取token失败: {e}")

        if not self.token or datetime.datetime.now() >= self.token_expiry or force:
            await _get_access_token()

    @print_execution_time
    async def submit_business_request(self, msg_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.get_access_token()
        result = {}
        try:
            logger.info(f"msg_id = {msg_id}, 寿险中控入参 = {params}")
            # token失效重试一次
            for _ in range(2):
                api_url = self.bonus_chat_addr.format(access_token=self.token)
                response = await get_client().post(api_url, json=params)
                result = response.json()
                if result.get("ret", "") == "13012":
                    await self.get_access_token(force=True)
                    logger.info(f"{msg_id}, 寿险中控token失效，重新获取！")
                else:
                    logger.info(f"msg_id = {msg_id}, 寿险中控返回: {result}")
                    return result

            raise Exception(f"寿险中控访问失败: {result.get('msg', '未知错误')}")
        except Exception as e:
            raise Exception(f"寿险中控访问失败: {e}")

    # DEPRECATED: 用 submit_business_request 代替，保留至下次 release 后删除（命名规范整改 2026-05）
    business_deal = submit_business_request


# DEPRECATED: 用 BonusChatClient 代替，保留至下次 release 后删除（命名规范整改 2026-05）
BonusChatAgent = BonusChatClient
