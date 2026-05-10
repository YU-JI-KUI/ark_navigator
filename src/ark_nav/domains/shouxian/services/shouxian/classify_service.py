"""寿险意图分类策略（调用 IntentClassifierDeployment）。

从 shouxian_nav_service.py 拆分而来（2026-05），保持原 class 行为一字不改。
2026-05 命名规范整改：
- 原类名 ClassifyService → IntentClassificationStrategy（更贴切：实际是策略选择器）
- 原方法名 shouxian_classify_intent → classify_intent（去冗余 shouxian 前缀，类已在 shouxian 包下）
- 旧名作为 alias 保留至下次 release。

负责：
- 包装 IntentRequest 调用大模型分类
- 缓存层：aiocache 600s TTL，namespace=shouxian, noself=True（实例间共享）
"""
import os

from aiocache import cached
from aiocache.serializers import StringSerializer

from ark_nav.core.utils.nav_logger import get_logger, print_execution_time
from ark_nav.domains.shouxian.router_schemas import IntentRequest, IntentResult
from ark_nav.domains.shouxian.services.shouxian._history_utils import (
    LIFE_INSURANCE,
    REJECTION,
)

logger = get_logger(__name__)


class IntentClassificationStrategy:

    def __init__(self, shouxian_intent_agent):
        self.shouxian_intent_agent = shouxian_intent_agent

    @print_execution_time
    async def classify_intent(self, msg_id: str, message: str, reject_reconfirm, history):
        """
        调用大模型平台，如果结果不是【拒识】or【寿险意图】则默认【寿险意图】
        """
        logger.info(f"{msg_id}, 模型入参: {message}")
        result = await self._classify_intent(message, reject_reconfirm, history)
        logger.info(f"{msg_id}, 模型识别结果: {result}")

        if result in [REJECTION]:
            return REJECTION
        elif result in [LIFE_INSURANCE]:
            return LIFE_INSURANCE
        else:
            return LIFE_INSURANCE

    # DEPRECATED: 用 classify_intent 代替，保留至下次 release 后删除（命名规范整改 2026-05）
    shouxian_classify_intent = classify_intent

    @cached(ttl=600, namespace="shouxian", serializer=StringSerializer(), noself=True)
    async def _classify_intent(self, message: str, reject_reconfirm, history):
        request = IntentRequest(
            app_key=os.getenv("APP_KEY"),
            app_secret=os.getenv("APP_SECRET"),
            user_message=message,
            reject_reconfirm=reject_reconfirm,
            history=history
        )
        response: IntentResult = await self.shouxian_intent_agent.classify_intent.remote(request)
        return response.result


# DEPRECATED: 用 IntentClassificationStrategy 代替，保留至下次 release 后删除（命名规范整改 2026-05）
ClassifyService = IntentClassificationStrategy
