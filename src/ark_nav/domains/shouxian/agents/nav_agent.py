"""寿险小导航智能体 - 合并意图识别与导航功能"""
import os
import traceback
from typing import Dict, Any

from fastapi import HTTPException
from ray import serve

from ark_nav.core.utils.nav_logger import get_logger, setup_logging, print_execution_time
from ark_nav.core.utils.httpx_deployment_decorator import with_http_client

from ark_nav.domains.shouxian.router_schemas import (
    ChatCompletionRequest,
    AgentPfmKbRequest,
    SearchIntentRequest,
    IntentRequest,
    IntentResult,
)
from ark_nav.domains.shouxian.services.shouxian_nav_service import ShouXianNavService
from ark_nav.core.services.agent_pfm_kb_service import AgentPfmKbService
from ark_nav.domains.shouxian.intent_classifier_advance import IntentClassifier
from ark_nav.domains.shouxian.intent_classifier_simple import classify_user_intent

logger = get_logger(__name__)

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 10))
INITIAL_REPLICAS = int(os.getenv("RAY_INITIAL_REPLICAS", 10))


@serve.deployment(
    name="NavAgentDeployment",
    max_ongoing_requests=20,
    ray_actor_options={
        "num_cpus": 0.5,
    },
    autoscaling_config={
        "min_replicas": MIN_REPLICAS,
        "max_replicas": 16,
        "initial_replicas": INITIAL_REPLICAS,
        "target_ongoing_requests": 5,
        "upscale_delay_s": 3,
        "downscale_delay_s": 60,
        "upscaling_factor": 1.0,
    }
)
@with_http_client()
class NavAgentDeployment:
    """寿险导航 Agent：包含意图识别 + 主对话编排"""

    def __init__(self, rag_models_handle):
        setup_logging()
        self.agent_pfm_kb_svc = AgentPfmKbService(
            rag_models_handle, domain="shouxian", kg_id=os.getenv("SHOUXIAN_AGENT_PLATFORM_KG_ID")
        )
        # 把自身作为 intent agent 注入，让 ClassifyService 进程内直接调用
        self.svc = ShouXianNavService(self, self.agent_pfm_kb_svc)

    async def process(self, request: ChatCompletionRequest):
        logger.info(f"msg_id = {request.msg_id}, Request Payload = {request}")
        response = await self.svc.run(msg_id=request.msg_id, request=request)
        return response

    async def reset_faiss_index(self, request: AgentPfmKbRequest) -> Dict[str, Any]:
        try:
            await self.agent_pfm_kb_svc.load_data(request.kg_id, request.is_reload)
            return {"status": "success"}
        except Exception as e:
            traceback.print_exc()
            logger.error(f"重置寿险 FAISS 索引异常:{str(e)}")
            return {"status": f"failed -> {str(e)}"}

    async def search(self, request: SearchIntentRequest):
        logger.info(f"Search API: {request.msg_id}, User request: {request}")
        response = await self.svc.search(request=request)
        return response

    @print_execution_time
    async def classify_intent(self, request: IntentRequest) -> IntentResult:
        try:
            if request.reject_reconfirm:
                logger.debug("reject_reconfirm is True, call classify_user_intent_advance")
                recognizer = IntentClassifier(request.app_key, request.app_secret)
                return await recognizer.classify_user_intent_advance(
                    current_query=request.user_message,
                    history=request.history,
                )
            else:
                logger.debug("reject_reconfirm is False, call classify_user_intent")
                result = await classify_user_intent(
                    app_key=request.app_key,
                    app_secret=request.app_secret,
                    user_message=request.user_message,
                )
                return IntentResult(result=result, source="direct")

        except Exception as e:
            logger.error(f"分类失败: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"分类失败: {str(e)}")
