import os
import time
from typing import List, Optional, Dict, Any
from ray import serve

from ark_nav.core.services.xiezhi_http import call_bigmodel_api, fetch_rag
from ark_nav.core.utils.nav_logger import get_logger, setup_logging
from ark_nav.domains.shouxian.router_schemas import IntentResult
from ark_nav.core.utils.llm_platform_config import LLMPlfConfig
from ark_nav.domains.yanglaoxian.router_schemas import YLXRequest, YLXResponse, XiaoAnRobotRequests, AgentPfmKbRequest
from ark_nav.domains.yanglaoxian.services.onekey_service import OneKeyService, XiaoAnRobot
from ark_nav.core.utils.httpx_deployment_decorator import with_http_client
from ark_nav.core.services.agent_pfm_kb_service import AgentPfmKbService

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


@serve.deployment(
    name="NavYLXAgentDeployment",
    ray_actor_options={
        "num_cpus": 0.5,
    },
    autoscaling_config={
        "min_replicas": 1,
        "max_replicas": 4,
        "target_num_ongoing_requests_per_replica": 10
    }
)
@with_http_client()
class NavYLXAgentDeployment:

    def __init__(self, rag_models_handle):
        setup_logging()
        self.rag_models_handle = rag_models_handle
        self.app_key = LLMPlfConfig.YLX_LLM_APP_KEY
        self.app_secret = LLMPlfConfig.YLX_LLM_APP_SECRET
        self.scene_id = LLMPlfConfig.YLX_LLM_SCENE_ID
        self.system_prompt = os.getenv("YLX_PROMPT", DEFAULT_PROMPT)
        self.robot = XiaoAnRobot()
        self.agent_pfm_kb_svc = AgentPfmKbService(
            rag_models_handle, domain="yanglaoxian", kg_id=os.getenv("AGENT_PLATFORM_KG_ID"))
        self.onekey_svc = OneKeyService(self.agent_pfm_kb_svc)
        # self.agent_pfm_kb_svc.load_index()

    async def process(self, query: str, msg_id: str = None) -> IntentResult:
        try:
            start_time = time.time()

            # 1. intention check via RAG
            enable_local_kg = os.getenv("ENABLE_LOCAL_KG", "False").strip().lower() == "true"
            if enable_local_kg:
                knowledge = await self.agent_pfm_kb_svc.search(query=query, top_k=1, kb_type="faq", kb_labels=['hotfix'])
                result = knowledge[0].get("answer") if len(knowledge) >= 1 else None
            else:
                result = await fetch_rag(query, kb_type=["faq"], labels=['hotfix'])

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
            logger.error(f"{msg_id}, 请求异常:{str(e)}", exc_info=True)
            default_resp = IntentResult(
                result="养老险意图",
                source="direct",
                extra={
                    "errors": str(e)
                }
            )
            return default_resp

    async def run(self, request: YLXRequest) -> YLXResponse:
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
            logger.error(f"{request.msg_id}, 请求异常:{str(e)}", exc_info=True)
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

    async def reset_faiss_index(self, request: AgentPfmKbRequest) -> Dict[str, Any]:
        try:
            await self.agent_pfm_kb_svc.load_data(request.kg_id, request.is_reload)
            return {"status": "success"}
        except Exception as e:
            logger.error(f"重置养老险 FAISS 索引异常:{str(e)}", exc_info=True)
            return {"status": f"failed -> {str(e)}"}
