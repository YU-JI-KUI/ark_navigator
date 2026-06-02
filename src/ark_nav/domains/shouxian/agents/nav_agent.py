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

# 寿险 Agent 副本配置
# - min=3：日常低峰够用，autoscaling 会在压力大时自动扩容到 max
# - max=16：覆盖大促等峰值；如果常规也撑不住，再调高这个上限
# - target_ongoing=8：每副本平均处理 8 个并发请求时触发扩容
# - downscale_delay=300：缩容更慢，避免日常流量起伏导致频繁扩缩
# - upscaling_factor=1.5：突发流量时扩容更激进（默认 1.0 是线性增长）
_SHOUXIAN_AGENT_MIN_REPLICAS = int(os.getenv("SHOUXIAN_AGENT_MIN_REPLICAS", 3))
_SHOUXIAN_AGENT_MAX_REPLICAS = int(os.getenv("SHOUXIAN_AGENT_MAX_REPLICAS", 16))


@serve.deployment(
    name="NavAgentDeployment",
    max_ongoing_requests=20,
    # 加 user_config 触发 Ray Serve 在副本启动时自动调 reconfigure
    # 这是"保证每个副本都启动 scheduler"的关键——不依赖业务请求触发
    user_config={},
    ray_actor_options={
        "num_cpus": 0.5,
    },
    autoscaling_config={
        "min_replicas": _SHOUXIAN_AGENT_MIN_REPLICAS,
        "max_replicas": _SHOUXIAN_AGENT_MAX_REPLICAS,
        "target_ongoing_requests": 8,
        "upscale_delay_s": 3,
        "downscale_delay_s": 300,
        "upscaling_factor": 1.5,
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
            # 寿险独立模式覆盖：未设置则走全局 KB_MODE；设置后只影响寿险
            mode=os.getenv("SHOUXIAN_KB_MODE"),
        )
        # 同步阻塞等索引就绪：LOCAL 拉远程建索引，REMOTE 立即返回
        bootstrap_knowledge_base(self.knowledge_base)
        # 把自身作为 intent agent 注入，让 ClassifyService 进程内直接调用
        self.svc = ShouXianNavService(self, self.knowledge_base)
        # scheduler 实例此处构造，启动延迟到 reconfigure（在 actor event loop 上跑）
        self._sync_scheduler = KnowledgeBaseSyncScheduler(self.knowledge_base)
        self._scheduler_started = False

    async def reconfigure(self, user_config) -> None:
        """Ray Serve 副本启动完成后自动调用一次，跑在 actor 自己的 event loop 上。

        这是"保证 scheduler 必启动"的主路径：
        - 不依赖业务请求触发（懒启动模式下流量不均副本可能永不启动）
        - 跑在 actor loop 上（避免独立线程跨 event loop 的 httpx client 问题）
        - 重复调用安全（start_async 内部有幂等检查）
        """
        logger.info(f"NavAgentDeployment.reconfigure triggered, starting scheduler")
        await self._ensure_scheduler_started()

    async def _ensure_scheduler_started(self) -> None:
        """业务方法兜底入口：万一 reconfigure 未触发（极端场景），首次业务请求时仍能启动"""
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
