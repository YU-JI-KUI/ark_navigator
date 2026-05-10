from typing import Any, Dict, List, Optional, Union
import json
import re
import copy
import datetime
import os
import traceback
from aiocache import cached
from aiocache.serializers import StringSerializer
from dotenv import load_dotenv
load_dotenv()

from ark_nav.core.utils.nav_logger import get_logger, print_execution_time
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.domains.shouxian.router_schemas import ChatCompletionRequest, ChatCompletionResponse, IntentRequest, IntentResult, SearchIntentRequest
from ark_nav.core.services.xiezhi_http import fetch_rag

LIFE_INSURANCE = "寿险意图"
REJECTION = "拒识"

logger = get_logger(__name__)

def _extract_by_path(data: Any, path: str) -> Optional[Union[Any, List[Any]]]:
    """通过路径字符串提取数据，自动处理数组索引和通配符"""
    if data is None:
        return None
    tokens = re.split(r'\.(?![^\[]*\])', path)
    current = data
    for i, token in enumerate(tokens):
        if current is None:
            return None
        match = re.match(r'^(.+?)\[(\d+|\*)\]$', token)
        if match:
            key, index = match.groups()
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
            if not isinstance(current, list) or len(current) == 0:
                return None
            if index == '*':
                remaining_path = '.'.join(tokens[i+1:])
                if remaining_path:
                    results = []
                    for item in current:
                        result = _extract_by_path(item, remaining_path)
                        if result is not None:
                            if isinstance(result, list):
                                results.extend(result)
                            else:
                                results.append(result)
                    return results if results else None
                else:
                    return current
            else:
                idx = int(index)
                if idx >= len(current):
                    return None
                current = current[idx]
        else:
            if isinstance(current, dict):
                current = current.get(token)
            else:
                return None
    if current is None:
        return None
    if isinstance(current, str) and not current.strip():
        return None
    if isinstance(current, (list, dict)) and len(current) == 0:
        return None
    return current


def _extract_card_content(card: Dict[str, Any]) -> Optional[Dict]:
    """从卡片中提取内容，按优先级尝试多个路径"""
    path_configs = [
        ("faq_complex", "data.blocks[0].contents[0].data"),
        ("faq_simple", "data.detail[0].content"),
        ("service", "data.blocks[0].contents[0].data.desc"),
        ("kg_2", "data.fullName"),
        ("disease", "data.detail[0].disease_knowledge"),
        ("skill", "data.cardList[0].title"),
        ("mutiple_kg_1", "data.answer"),
        ("task", "data.searchList[0].subList[*].data.name"),
        ("default", "msg"),
    ]
    for source_type, path in path_configs:
        content = _extract_by_path(card, path)
        if content is not None:
            return {
                'source_type': source_type,
                'content': content,
                'card_type': card.get('type', 'unknown'),
            }
    return None


def _content_to_text(content: Any) -> str:
    """将提取的内容转换为文本"""
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        for key in ['text', 'content', 'title', 'desc', 'description', 'value','name']:
            if key in content and content[key]:
                return str(content[key])
        return str(content)
    elif isinstance(content, list):
        texts = [_content_to_text(item) for item in content]
        return ' | '.join(filter(None, texts))
    else:
        return str(content)


def process_history(contexts: List):
    history = copy.copy(contexts)
    if len(contexts) <= 1:
        history = []
    else:
        base_history = []
        for idx in reversed(range(len(history))):
            if "user" == history[idx]["role"]:
                item_content = history[idx]["content"]
                user_message = item_content.get("message")
                if user_message:
                    base_history.append({"text": user_message, "role": "user"})
            if "ai" == history[idx]["role"]:
                try:
                    item_content = history[idx]["content"]
                    card_content = item_content.get("card_content", {})
                    if card_content:
                        extracted = _extract_card_content(card_content)
                        if extracted:
                            text = _content_to_text(extracted['content'])
                            if text:
                                base_history.append({"text": text, "role": "ai"})
                except (IndexError, TypeError, AttributeError):
                    pass
        history = base_history
    return history


def _parse_rag_answer(rag_answer: str | None) -> dict[str, str]:
    """
    解析 rag_answer 字符串，格式如：ACTIVITY-汇赚唤我领平安好礼
    返回结构化字典：
    {
        "sa_business_type": "ACTIVITY",
        "sa_business_data": "汇赚唤我领平安好礼"
    }
    若输入无效，返回默认空值。
    """
    if not rag_answer or not isinstance(rag_answer, str):
        return {"sa_business_type": "", "sa_business_data": ""}

    parts = rag_answer.strip().split("-", maxsplit=1)

    if len(parts) < 2:
        return {"sa_business_type": parts[0] if parts else "", "sa_business_data": ""}

    sa_business_type, sa_business_data = parts[0], parts[1]

    return {
        "sa_business_type": sa_business_type,
        "sa_business_data": sa_business_data
    }


class ShouXianNavService:

    def __init__(self, shouxian_intent_agent, agent_pfm_kb_svc):
        self.intent_recognition_service = IntentRecognitionService()
        self.rag_service = RagService(agent_pfm_kb_svc)
        self.classify_service = ClassifyService(shouxian_intent_agent)

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
                result = await self._do_intent_recognition(request, state)
            elif intention == "rejection":
                logger.info(f"msg_id = {request.msg_id}, 已经存在意图，直接拒识")
                result = self.get_rejection()
            else:
                logger.info(f"msg_id = {request.msg_id}, 正常流程：知识库 -> Intent Model -> 寿险中台 -> 后处理 or 拒识")
                rag_answer = await self.rag_service.fetch_rag(msg_id=request.msg_id, message=request.message)
                result = _parse_rag_answer(rag_answer)
                if result.get("sa_business_type") != "ACTIVITY":
                    if rag_answer in [LIFE_INSURANCE]:
                        result = await self._do_intent_recognition(request, state)
                    elif rag_answer in [REJECTION]:
                        result = self.get_rejection()
                    else:
                        model_return = await self.classify_service.shouxian_classify_intent(
                            msg_id=msg_id, message=request.message, reject_reconfirm=True, history=state.get("history"))
                        if model_return in [LIFE_INSURANCE]:
                            result = await self._do_intent_recognition(request, state)
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
            traceback.print_exc()
            logger.error(f"{request.msg_id}, 请求异常:{str(e)}")
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
                model_return = await self.classify_service.shouxian_classify_intent(request.msg_id, request.message, request.reject_reconfirm, history=[])
                if model_return in [LIFE_INSURANCE]:
                    final_result = "life_insurance"
                else:
                    final_result = "rejection"

            return self.post_search(final_result)

        except Exception as e:
            traceback.print_exc()
            logger.error(f"{request.msg_id}, 请求异常:{str(e)}")
            return self.post_search(str(e))

    async def _do_intent_recognition(self, request: ChatCompletionRequest, state: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.intent_recognition_service.run(
            req_id=request.msg_id,
            to_agent=state.get("to_agent", ""),
            bu_channel=request.buChannel,
            chat_agent_req=state.get("chat_agent_req"),
        )
        return result


class BonusChatAgent:

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
    async def business_deal(self, msg_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
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


class IntentRecognitionService:
    rejection_card_type_list = []

    def __init__(self):
        self.bonus_chat_agent = BonusChatAgent()

    def _postprocess(self, bonus_response: Dict[str, Any], to_agent: str, bu_channel: Dict[str, Any]) -> Dict[str, Any]:
        cross_bu_check = "life_insurance"
        card_content = bonus_response.get("data")
        card_content = card_content if card_content else {}
        card_type = card_content.get("type") if card_content else ""
        open_id = card_content.get("openId") if card_content else ""
        # 生存金领取和理赔报案流程中断，需重置to_agent
        sx_to_agent = card_content.get("toAgent")
        if to_agent in ("shengcunjin-claim-E031", "claim-report") and sx_to_agent == "":
            to_agent = ""

        if bu_channel.get("channel") != "shouXian":
            if card_type in self.rejection_card_type_list:
                cross_bu_check = "rejection"
                card_type = "shouXian"
                # 拒识清空
                card_content = {}
                to_agent = ""

        return {
            "source_bu_type": card_type,
            "service_type": cross_bu_check,
            "code": bonus_response.get("code"),
            "code_msg": bonus_response.get("msg"),
            "card_content": card_content,
            "card_type": card_type,
            "open_id": open_id,
            "to_agent": to_agent
        }

    async def run(self, req_id: str, to_agent: str, bu_channel: Dict[str, Any], chat_agent_req: Dict[str, Any]):
        request_body = {
            "reqId": req_id,
            "toAgent": to_agent,
            "chatAgentReq": chat_agent_req
        }
        response = await self.bonus_chat_agent.business_deal(msg_id=req_id, params=request_body)
        return self._postprocess(response, to_agent, bu_channel)


class RagService:

    def __init__(self, agent_pfm_kb_svc):
        self.agent_pfm_kb_svc = agent_pfm_kb_svc

    @print_execution_time
    async def fetch_rag(self, msg_id: str, message: str):
        rag_answer = await self._fetch_rag_remote(message=message)
        rag_answer = rag_answer if rag_answer else ""
        logger.info(f'msg_id = {msg_id} message = {message} 知识库返回结果 = {rag_answer}')
        return rag_answer

    @cached(ttl=600, namespace="shouxian", serializer=StringSerializer(), noself=True)
    async def _fetch_rag_remote(self, message: str):
        enable_local_kg = os.getenv("ENABLE_LOCAL_KG", "False").strip().lower() == "true"
        if enable_local_kg:
            logger.info("query from local knowledge base")
            data = await self.agent_pfm_kb_svc.search(query=message, score_threshold=0.9, top_k=1, kb_type="faq",
                                                       use_rerank=False)
            rag_answer = data[0].get("answer") if len(data) >= 1 else None
            return rag_answer
        else:
            logger.info("query from remote knowledge base")
            rag_answer = await fetch_rag(query=message, kb_type=["faq"], kb_ids=[os.getenv("SHOUXIAN_AGENT_PLATFORM_KG_ID")])
            return rag_answer


class ClassifyService:

    def __init__(self, shouxian_intent_agent):
        self.shouxian_intent_agent = shouxian_intent_agent

    @print_execution_time
    async def shouxian_classify_intent(self, msg_id: str, message: str, reject_reconfirm, history):
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
