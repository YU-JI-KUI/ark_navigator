"""寿险小导航智能体代码化入口文件 - 占位符"""
import os
from typing import Dict, Any
from ray import serve

from ark_nav.core.utils.nav_logger import get_logger
from ark_nav.core.utils.httpx_deployment_decorator import with_http_client

from ark_nav.domains.shouxian.router_schemas import ChatCompletionRequest, AgentPfmKbRequest, SearchIntentRequest
from ark_nav.domains.shouxian.services.shouxian_nav_service import ShouxianNavOrchestrator
from ark_nav.core.services.agent_pfm_kb_service import KnowledgeBaseService

logger = get_logger(__name__)

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 10))
INITIAL_REPLICAS = int(os.getenv("RAY_INITIAL_REPLICAS", 10))

# This is placeholder, uncomment this to implement the nav navigator agent
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
    }
)
@with_http_client()
class NavAgentDeployment:
    """单级Agent：直接调用BB模型"""

    def __init__(self, rag_models_handle, shouxian_intent_agent):
        self.agent_pfm_kb_svc = KnowledgeBaseService(rag_models_handle, domain="shouxian", kg_id=os.getenv("SHOUXIAN_AGENT_PLATFORM_KG_ID"))
        self.svc = ShouxianNavOrchestrator(shouxian_intent_agent, self.agent_pfm_kb_svc)

    async def process(self, request: ChatCompletionRequest):
        logger.info(f"msg_id = {request.msg_id}, Request Payload = {request}")
        response = await self.svc.run(msg_id=request.msg_id, request=request)
        return response

    async def reset_faiss_index(self, request: AgentPfmKbRequest) -> Dict[str, Any]:
        try:
            await self.agent_pfm_kb_svc.load_data(request.kg_id, request.is_reload)
            return {"status": "success"}
        except Exception as e:
            logger.error(f"重置寿险 FAISS 索引异常:{str(e)}", exc_info=True)
            return {"status": f"failed -> {str(e)}"}

    async def search(self, request: SearchIntentRequest):
        logger.info(f"Search API: {request.msg_id}, User request: {request}")
        response = await self.svc.search(request=request)
        return response
