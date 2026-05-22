"""寿险小导航智能体 - 合并意图识别与导航功能"""
import os

from fastapi import HTTPException
from ray import serve

from ark_nav.core.utils.nav_logger import (
    get_logger,
    setup_logging,
    print_execution_time,
    propagate_trace,
)
from ark_nav.core.utils.httpx_deployment_decorator import with_http_client

from ark_nav.domains.shouxian.router_schemas import (
    ChatCompletionRequest,
    SearchIntentRequest,
    IntentRequest,
    IntentResult,
)
from ark_nav.domains.shouxian.services.shouxian_nav_service import ShouXianNavService
from ark_nav.core.services.knowledge_base import build_knowledge_base, bootstrap_knowledge_base
from ark_nav.core.services.knowledge_base_scheduler import KnowledgeBaseSyncScheduler
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

    def __init__(self, embedding_model_handle):
        setup_logging()
        self.knowledge_base = build_knowledge_base(
            embedding_model_handle=embedding_model_handle,
            domain="shouxian",
            kg_id=os.getenv("SHOUXIAN_AGENT_PLATFORM_KG_ID"),
        )
        # 同步阻塞等索引就绪：LOCAL 拉远程建索引，REMOTE 立即返回
        bootstrap_knowledge_base(self.knowledge_base)
        # 把自身作为 intent agent 注入，让 ClassifyService 进程内直接调用
        self.svc = ShouXianNavService(self, self.knowledge_base)
        # 调度器在首个请求时懒启动，确保 task 跑在 actor 真实 event loop 上
        self._sync_scheduler = KnowledgeBaseSyncScheduler(self.knowledge_base)
        self._scheduler_started = False

    async def _ensure_scheduler_started(self) -> None:
        if not self._scheduler_started:
            self._scheduler_started = True
            await self._sync_scheduler.start_async()

    @propagate_trace
    async def process(self, request: ChatCompletionRequest):
        await self._ensure_scheduler_started()
        logger.info(f"nav_agent.process msg_id={request.msg_id}")
        response = await self.svc.run(msg_id=request.msg_id, request=request)
        return response

    @propagate_trace
    async def search(self, request: SearchIntentRequest):
        await self._ensure_scheduler_started()
        logger.info(f"nav_agent.search msg_id={request.msg_id}")
        response = await self.svc.search(request=request)
        return response

    @propagate_trace
    @print_execution_time
    async def classify_intent(self, request: IntentRequest) -> IntentResult:
        await self._ensure_scheduler_started()
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
