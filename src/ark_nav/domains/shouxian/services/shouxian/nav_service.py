"""寿险导航主服务编排器。

从 shouxian_nav_service.py 拆分而来（2026-05），保持原 class 行为一字不改。
2026-05 命名规范整改：
- 原类名 ShouXianNavService → ShouxianNavOrchestrator
- 修复 PEP 8 大小写（"ShouXian" 应为 "Shouxian"）
- 用 Orchestrator 后缀更准确反映"编排器"角色（不是简单 Service）
- 旧名作为 alias 保留至下次 release。

负责：
- 主流程 run()：意图先验 → RAG 快速命中 → 大模型分类 → 寿险中控
- search()：仅意图分类，不走中控
- 三个 service 的依赖注入装配
"""
import datetime
import json
from typing import Any, Dict

from ark_nav.core.utils.nav_logger import get_logger, print_execution_time
from ark_nav.domains.shouxian.router_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    SearchIntentRequest,
)
from ark_nav.domains.shouxian.services.shouxian._history_utils import (
    LIFE_INSURANCE,
    REJECTION,
    _parse_rag_answer,
    process_history,
)
from ark_nav.domains.shouxian.services.shouxian.classify_service import IntentClassificationStrategy
from ark_nav.domains.shouxian.services.shouxian.intent_recognition import (
    IntentRecognitionService,
)
from ark_nav.domains.shouxian.services.shouxian.rag_service import ShouxianRagRetriever

logger = get_logger(__name__)


class ShouxianNavOrchestrator:

    def __init__(self, shouxian_intent_agent, agent_pfm_kb_svc):
        self.intent_recognition_service = IntentRecognitionService()
        self.rag_service = ShouxianRagRetriever(agent_pfm_kb_svc)
        self.classify_service = IntentClassificationStrategy(shouxian_intent_agent)

    @staticmethod
    def postprocess(request: ChatCompletionRequest, response: ChatCompletionResponse) -> Dict[str, Any]:
        return {
            "code": "success",
            "data": [
                {
                    "round_id": request.extrainfo.get("traceId"),
                    "message_id": request.msg_id,
                    "conversation_id": request.session_id,
                    "content_type": "json",
                    "content": response.model_dump_json(),
                    "trackId": request.extrainfo.get("traceId"),
                }
            ]
        }

    @staticmethod
    def post_search(result: str) -> Dict[str, Any]:
        return {
            "code": "success",
            "data": {
                "service_type": result
            }
        }

    @staticmethod
    def preprocess_input(request: ChatCompletionRequest) -> Dict[str, Any]:
        history = process_history(request.contexts)
        bu_channel = request.buChannel
        open_id = request.extrainfo.get("openId")
        trace_id = request.extrainfo.get("traceId", "")
        data = request.extrainfo.get("data")
        if "extraParams" in request.extrainfo:
            data_obj = data if data else {"inputTypes": "text", "msg": request.message, "extraParams": request.extrainfo.get("extraParams")}
        else:
            data_obj = data if data else {"inputTypes": "text", "msg": request.message}
        if "nextInput" in request.extrainfo:
            next_input = request.extrainfo.get("nextInput", {})
            data_str = json.dumps(next_input.get("data", {}), ensure_ascii=False, indent=2)
        else:
            data_str = json.dumps(data_obj, ensure_ascii=False, indent=2)
        to_agent = request.to_agent
        card_params = request.card_params
        to_agent = "" if not card_params and to_agent in ("bonus-claim", "HONGLI") else to_agent
        agent_conversation_id = request.agent_conversation_id
        if len(to_agent) == 0:
            card_params = {}
            agent_conversation_id = None

        chat_agent_req = {
            "clientNo": request.extrainfo.get("clientNo"),
            "data": data_str,
            "reqId": request.msg_id,
            "source": request.extrainfo.get("source", "APP_SUPERAGENT"),
            "type": "200",
            "traceId": trace_id,
            "ssoTicket": request.extrainfo.get("ssoTicket", ""),
            "userIp": request.extrainfo.get("userIp"),
            "osType": request.extrainfo.get("osType")
        }

        if request.to_agent in ("shengcunjin-claim-E031", "claim-report"):
            chat_agent_req = request.extrainfo

        return {
            "messages": [{"role": "user", "content": request.message}] + [
                {"role": m["role"], "content": m["text"]} for m in history[::-1]
            ],
            "client_no": request.extrainfo.get("clientNo"),
            "intention": request.extrainfo.get("intention"),
            "open_id": open_id,
            "history": history[::-1],
            "data": data_str,
            "agent_conversation_id": agent_conversation_id,
            "source": request.extrainfo.get("source", "APP_SUPERAGENT"),
            "card_params": card_params,
            "to_agent": to_agent,
            "chat_agent_req": chat_agent_req,
            "bu_channel": bu_channel,
            "trace_id": trace_id
        }

    @staticmethod
    def get_rejection() -> Dict[str, Any]:
        return {
            "service_type": "rejection",
            "to_agent": ""
        }

    @print_execution_time
    async def run(self, msg_id: str, request: ChatCompletionRequest):
        try:
            if not request.message:
                logger.warn(f"{msg_id}, Invalid request: Empty or invalid messages")
                result = self.postprocess(request, ChatCompletionResponse())
                return result

            state = self.preprocess_input(request)
            open_id = state.get("open_id")
            intention = state.get("intention")

            if intention == "life_insurance":
                logger.info(f"msg_id = {request.msg_id}, 已经存在意图，直接分发给寿险中台")
                result = await self._recognize_intent(request, state)
            elif intention == "rejection":
                logger.info(f"msg_id = {request.msg_id}, 已经存在意图，直接拒识")
                result = self.get_rejection()
            else:
                logger.info(f"msg_id = {request.msg_id}, 正常流程：知识库 -> Intent Model -> 寿险中台 -> 后处理 or 拒识")
                rag_answer = await self.rag_service.fetch_rag(msg_id=request.msg_id, message=request.message)
                result = _parse_rag_answer(rag_answer)
                if result.get("sa_business_type") != "ACTIVITY":
                    if rag_answer in [LIFE_INSURANCE]:
                        result = await self._recognize_intent(request, state)
                    elif rag_answer in [REJECTION]:
                        result = self.get_rejection()
                    else:
                        model_return = await self.classify_service.classify_intent(
                            msg_id=msg_id, message=request.message, reject_reconfirm=True, history=state.get("history"))
                        if model_return in [LIFE_INSURANCE]:
                            result = await self._recognize_intent(request, state)
                        else:
                            result = self.get_rejection()

            final_result = self.postprocess(request, ChatCompletionResponse(
                bu_type="shouxian",
                source_bu_type=result.get("source_bu_type", ""),
                service_type=result.get("service_type", ""),
                is_chat="0",
                timestamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                code=result.get("code", ""),
                code_msg=result.get("code_msg", ""),
                card_content=result.get("card_content", {}),
                to_agent=result.get("to_agent", ""),
                agent_conversation_id=result.get("agent_conversation_id", ""),
                openId=open_id or result.get("open_id", ""),
                sa_business_type=result.get("sa_business_type", ""),
                sa_business_data=result.get("sa_business_data", "")
            ))
            return final_result

        except Exception as e:
            logger.error(f"{request.msg_id}, 请求异常:{str(e)}", exc_info=True)
            final_result = self.postprocess(request, ChatCompletionResponse(code_msg=str(e)))
            return final_result

    @print_execution_time
    async def search(self, request: SearchIntentRequest):
        final_result = "life_insurance"
        try:
            if not request.message:
                logger.warn(f"Invalid request: Empty or invalid messages")
                return final_result

            rag_answer = await self.rag_service.fetch_rag(msg_id=request.msg_id, message=request.message)
            if rag_answer in [LIFE_INSURANCE]:
                final_result = "life_insurance"
            elif rag_answer in [REJECTION]:
                final_result = "rejection"
            else:
                model_return = await self.classify_service.classify_intent(request.msg_id, request.message, request.reject_reconfirm, history=[])
                if model_return in [LIFE_INSURANCE]:
                    final_result = "life_insurance"
                else:
                    final_result = "rejection"

            return self.post_search(final_result)

        except Exception as e:
            logger.error(f"{request.msg_id}, 请求异常:{str(e)}", exc_info=True)
            return self.post_search(str(e))

    async def _recognize_intent(self, request: ChatCompletionRequest, state: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.intent_recognition_service.run(
            req_id=request.msg_id,
            to_agent=state.get("to_agent", ""),
            bu_channel=request.buChannel,
            chat_agent_req=state.get("chat_agent_req"),
        )
        return result


# DEPRECATED: 用 ShouxianNavOrchestrator 代替（同时修复 PEP 8 大小写：ShouXian → Shouxian），
# 保留至下次 release 后删除（命名规范整改 2026-05）
ShouXianNavService = ShouxianNavOrchestrator
