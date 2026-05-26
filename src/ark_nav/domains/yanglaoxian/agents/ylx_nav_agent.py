import os
import time
from ray import serve
import traceback

from ark_nav.core.services.llm_platform_client import call_bigmodel_api
from ark_nav.core.utils.nav_logger import get_logger, setup_logging, propagate_trace
from ark_nav.domains.shouxian.router_schemas import IntentResult
from ark_nav.core.utils.llm_platform_config import LLMPlfConfig
from ark_nav.domains.yanglaoxian.router_schemas import YLXRequest, YLXResponse, XiaoAnRobotRequests
from ark_nav.domains.yanglaoxian.services.onekey_service import OneKeyService, XiaoAnRobot
from ark_nav.core.utils.httpx_deployment_decorator import with_http_client
from ark_nav.core.services.knowledge_base import build_knowledge_base, bootstrap_knowledge_base
from ark_nav.core.services.knowledge_base_scheduler import KnowledgeBaseSyncScheduler

DEFAULT_PROMPT = """
你是一个意图分类专家，你的职责仅限于"识别与判断"。你需要根据用户提问的'来源'和'问题'，进行以下意图的判断，禁止提供任何建议、解决方案或行动指引。
1、判断用户问题是否与养老险业务相关，回答'养老险意图'
2、判断用户问题是否与紧急救援服务相关，回答'紧急救援'
3、如果与以上均无关，回答'拒识'

# 输出格式：
养老险意图，紧急救援 或者 拒识 （三选一）
"""

QUERY_TEMPLATE = """
#来源：好福利app
#问题：{input}
"""

DEFAULT_CHANNEL = "好福利app"
logger = get_logger(__name__)

# 养老险 Agent 副本配置（QPS 远低于寿险）
# - min=1 / max=4：养老险流量小，1 副本日常够用，max=4 应对意外峰值
# - target=8：和寿险对齐，便于运维统一理解
# - downscale_delay=300：缩容更慢，避免抖动
_YLX_AGENT_MIN_REPLICAS = int(os.getenv("YLX_AGENT_MIN_REPLICAS", 1))
_YLX_AGENT_MAX_REPLICAS = int(os.getenv("YLX_AGENT_MAX_REPLICAS", 4))


@serve.deployment(
    name="NavYLXAgentDeployment",
    # 加 user_config 触发 Ray Serve 在副本启动时自动调 reconfigure
    # 用于在 actor event loop 上主动启动 scheduler，不依赖业务请求触发
    user_config={},
    ray_actor_options={
        "num_cpus": 0.5,
    },
    autoscaling_config={
        "min_replicas": _YLX_AGENT_MIN_REPLICAS,
        "max_replicas": _YLX_AGENT_MAX_REPLICAS,
        "target_num_ongoing_requests_per_replica": 8,
        "upscale_delay_s": 3,
        "downscale_delay_s": 300,
    }
)
@with_http_client()
class NavYLXAgentDeployment:

    def __init__(self, embedding_model_handle):
        setup_logging()
        self.embedding_model_handle = embedding_model_handle
        self.app_key = LLMPlfConfig.YLX_LLM_APP_KEY
        self.app_secret = LLMPlfConfig.YLX_LLM_APP_SECRET
        self.scene_id = LLMPlfConfig.YLX_LLM_SCENE_ID
        self.system_prompt = os.getenv("YLX_PROMPT", DEFAULT_PROMPT)
        self.robot = XiaoAnRobot()
        self.knowledge_base = build_knowledge_base(
            embedding_model_handle=embedding_model_handle,
            domain="yanglaoxian",
            kg_id=os.getenv("AGENT_PLATFORM_KG_ID"),
        )
        # 同步阻塞等索引就绪：LOCAL 拉远程建索引，REMOTE 立即返回
        bootstrap_knowledge_base(self.knowledge_base)
        self.onekey_svc = OneKeyService(self.knowledge_base)
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
        logger.info("NavYLXAgentDeployment.reconfigure triggered, starting scheduler")
        await self._ensure_scheduler_started()

    async def _ensure_scheduler_started(self) -> None:
        """业务方法兜底入口：万一 reconfigure 未触发（极端场景），首次业务请求时仍能启动"""
        if not self._scheduler_started:
            self._scheduler_started = True
            await self._sync_scheduler.start_async()

    @propagate_trace
    async def process(self, query: str, msg_id: str = None) -> IntentResult:
        await self._ensure_scheduler_started()
        try:
            start_time = time.time()

            # 1. intention check via RAG
            result = await self.knowledge_base.fetch_faq_answer(query=query, labels=["hotfix"])

            if result is not None:
                logger.info("shortcut from RAG")
                processing_time = (time.time() - start_time) * 1000
                return IntentResult(
                    result=result,
                    source="rag",
                    extra={
                        "processing_time_ms": processing_time
                    }
                )

            # 2. intention check with LLM
            question = QUERY_TEMPLATE.format(input=query)
            query = f"{self.system_prompt} {question}"
            logger.info(f"{msg_id}, 养老险意图识别Query: {question}")
            response = await call_bigmodel_api(
                query=query,
                scene_id=self.scene_id,
                app_key=self.app_key,
                app_secret=self.app_secret
            )

            result = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            logger.info(f"{msg_id}, 模型返回:{result}")
            processing_time = (time.time() - start_time) * 1000
            return IntentResult(
                result=result,
                source="direct",
                extra={
                    "processing_time_ms": processing_time
                }
            )

        except Exception as e:
            traceback.print_exc()
            logger.error(f"{msg_id}, 请求异常:{str(e)}")
            default_resp = IntentResult(
                result="养老险意图",
                source="direct",
                extra={
                    "errors": str(e)
                }
            )
            return default_resp

    @propagate_trace
    async def run(self, request: YLXRequest) -> YLXResponse:
        await self._ensure_scheduler_started()
        try:
            logger.info(f"{request.msg_id}, User request: {request}")
            message = request.message
            intent = await self.process(query=message, msg_id=request.msg_id)
            logger.info(f"{request.msg_id}, 【意图识别结果】: {intent}")
            if intent.result in ["养老险意图"]:
                result = await self.onekey_svc.process(
                    msg_id=request.msg_id,
                    message=message,
                    user_id=request.user_id,
                    channel=request.buChannel.get("channel", "ylXian")
                )
                return YLXResponse(
                    code=result.code,
                    code_msg=result.code_msg,
                    source_bu_type=result.source_bu_type,
                    card_content=result.card_content,
                    card_type=result.source,
                    service_type="",
                    extrainfo={},
                )
            else:
                return YLXResponse(
                    code="0",
                    code_msg="",
                    source_bu_type="ylXian",
                    card_content={},
                    card_type="ylXian",
                    service_type="rejection",
                    extrainfo={},
                )

        except Exception as e:
            traceback.print_exc()
            logger.error(f"{request.msg_id}, 请求异常:{str(e)}")
            default_resp = YLXResponse(
                code="-1",
                code_msg=str(e),
                source_bu_type="ylXian",
                card_content={},
                card_type="ylXian",
                service_type="rejection",
                extrainfo={},
            )
            return default_resp

