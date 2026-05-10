import json
import datetime
from dataclasses import fields
import os
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv()
from ark_nav.domains.yanglaoxian.router_schemas import OneKeyResult, XiaoAnRobotRequests, OneKeyLLMResult, KnowledgeInfo
from ark_nav.core.services.xiezhi_http import call_llm, fetch_rag
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time
from ark_nav.domains.yanglaoxian.prompts import ONEKEY_INTENT_CLASSIFIER
import copy

logger = get_logger("ark_nav_OneKey")


@print_execution_time
async def classify_user_intent(
        msg_id: str,
        scene_id: str,
        app_key: str,
        app_secret: str,
        user_message: str,
        agent_pfm_kb_svc
) -> OneKeyLLMResult:
    """
    调用 OpenAI 接口判断用户意图是否属于寿险范畴。

    Args:
        msg_id (str): 信息id
        scene_id (str)
        app_key (str): 应用密钥
        app_secret (str): 应用密钥
        user_message (str): 用户最新输入
        agent_pfm_kb_svc: 本地知识库服务
    """
    if not all([app_key, app_secret,user_message]):
        raise ValueError("缺少必要参数: user_message、APP_KEY、APP_SECRET")
    enable_local_kg = os.getenv("ENABLE_LOCAL_KG", "False").strip().lower() == "true"
    if enable_local_kg:
        data = await agent_pfm_kb_svc.search(query="养老险一键到底意图识别", top_k=1, kb_type="faq", use_rerank=False)
        search_result = data[0].get("answer") if len(data) >= 1 else None
        system_message = search_result or ONEKEY_INTENT_CLASSIFIER
    else:
        system_message = await fetch_rag(query="养老险一键到底意图识别", kb_type=["faq"]) or ONEKEY_INTENT_CLASSIFIER

    messages = [
        {
            "role": "system",
            "content": system_message
        },
        {
            "role": "user",
            "content": user_message
        }
    ]
    logger.info(f"{msg_id}, 意图识别Query: {messages}")
    try:
        response = await call_llm(
            query=messages,
            scene_id=scene_id,
            app_key=app_key,
            app_secret=app_secret
        )

        result = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        logger.info(f"{msg_id}, 模型返回:{result}")
        # 提取结果
        return OneKeyLLMResult(**json.loads(result))

    except Exception as e:
        logger.error(f"{msg_id}, 请求异常:{str(e)}")
        return OneKeyLLMResult()


class XiaoAnRobotClient:
    """
    小安机器人 HTTP 客户端。

    2026-05 命名规范整改：原类名 XiaoAnRobot，但实际是普通 HTTP 客户端
    （不是 LLM agent，是调用 ESG 接口的封装），重命名为 XiaoAnRobotClient，
    旧名作为 alias 保留至下次 release。
    """
    MENU_ITEMS = "7"  # 动态菜单

    def __init__(self):
        self.token = None
        self.token_expiry = datetime.datetime.now()
        self.xiaoan_chat_addr = os.getenv("ESG_XIAOAN_CHAT_ADDR")

    async def get_access_token(self, force=False):
        # access_token需要30天内失效

        async def _get_access_token():
            """获取 access token"""
            oauth_url = os.getenv("ESG_OAUTH_URL")
            client_id = os.getenv("ESG_CLIENT_ID")
            grant_type = os.getenv("ESG_GRANT_TYPE")
            client_secret = os.getenv("ESG_CLIENT_SECRET")
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
    async def chat(self, msg_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        await self.get_access_token()
        logger.info(f"{msg_id}, 小安机器人入参: {params}")
        result = {}
        try:
            # token失效重试一次
            for _ in range(2):
                api_url = self.xiaoan_chat_addr.format(access_token=self.token)
                response = await get_client().post(api_url, json=params)
                result = json.loads(response.text.replace('"data":"{', '"data":{').replace('}"}}', '}}}'))
                if result.get("ret") == "0":
                    logger.info(f"{msg_id}, 小安机器人返回结果: {result}")
                    return result.get("data")
                else:
                    await self.get_access_token(force=True)
            raise Exception(f"小安机器人访问失败: {result.get('msg', '未知错误')}")
        except Exception as e:
            raise Exception(f"小安机器人访问失败: {e}")


class OneKeyService:
    faiss_model = "faiss_index.index"
    knowledge_base = "ylx_onekey_knowledge_base.xlsx"

    def __init__(self, agent_pfm_kb_svc, t: float=0.85):
        self.t = t
        self.robot = XiaoAnRobotClient()
        self.scene_id = os.getenv("INTENT_REWRITE_SCENE_ID")
        self.app_key = os.getenv("INTENT_REWRITE_APP_KEY")
        self.app_secret = os.getenv("INTENT_REWRITE_APP_SECRET")
        self.agent_pfm_kb_svc = agent_pfm_kb_svc

    @print_execution_time
    async def get_onekey_result(self, msg_id: str, llm_result: OneKeyLLMResult, card_content) -> OneKeyResult:
        enable_local_kg = os.getenv("ENABLE_LOCAL_KG", "False").strip().lower() == "true"
        if enable_local_kg:
            data = await self.agent_pfm_kb_svc.search(query=llm_result.sub_intent, top_k=1, kb_type="table", use_rerank=False)
            search_result = data[0] if len(data) >= 1 else None
            logger.info(f"{msg_id}, 查询知识table: {search_result}")
            knowledge = copy.copy(search_result)
            knowledge["sub_category_i"] = knowledge.get("text")
        else:
            knowledge = await fetch_rag(query=llm_result.sub_intent, kb_type=["table"], score_threshold=self.t)

        if knowledge is None:
            logger.info(f"{msg_id}, 【非一键场景 - 无知识库配置】")
            return OneKeyResult(card_content=card_content)
        elif llm_result.task_type == OneKeyLLMResult.TASK_TYPE_INFO and card_content.get("answerType", "") == XiaoAnRobotClient.MENU_ITEMS:
            logger.info(f"{msg_id}, 【非一键场景 - 小安特殊answerType】")
            return OneKeyResult(card_content=card_content)
        else:
            try:
                logger.info(f"{msg_id}, 【进入一键场景】")
                knowledge = {field.name: knowledge.get(field.name) for field in fields(KnowledgeInfo)}
                info = KnowledgeInfo(**knowledge)
                answer = card_content.get("answer")
                answer = answer if llm_result.task_type == OneKeyLLMResult.TASK_TYPE_INFO else info.answer.strip()
                result = OneKeyResult(
                    card_content={
                        "category": info.category_i.strip(),
                        "sub_category": info.sub_category_i,
                        "type": info.type.strip(),
                        "answer": answer,
                        "title": info.title.strip(),
                        "sub_title": info.sub_title.strip(),
                        "button": info.button.strip(),
                        "link_key": info.link_key.strip(),
                        "link": info.link.strip(),
                        "answerType": card_content.get("answerType")
                    },
                    source="onekey"
                )
                logger.info(f"{msg_id}, 一键结果输出: {result}")
                return result
            except Exception as e:
                raise Exception(f"faiss索引和知识库文件不匹配: {e}")

    @print_execution_time
    async def process(self, msg_id: str, message: str, user_id: str, channel: str) -> OneKeyResult:
        payload = XiaoAnRobotRequests(
            repository_id=int(os.getenv("XIAOAN_REPOSITORY_ID")),
            question=message,
            user_id=user_id,
            label=["app", "好福利"]
        ).to_dict()
        data = await self.robot.chat(msg_id=msg_id, params=payload)
        if channel == "ylXian":
            llm_result = await classify_user_intent(
                msg_id=msg_id, scene_id=self.scene_id, app_key=self.app_key,
                app_secret=self.app_secret, user_message=message, agent_pfm_kb_svc=self.agent_pfm_kb_svc)
            if llm_result.domain == "其他" or llm_result.sub_intent == "其他":
                return OneKeyResult(card_content=data)
            else:
                result = await self.get_onekey_result(msg_id=msg_id, llm_result=llm_result, card_content=data)
                return result
        else:
            return OneKeyResult(card_content=data)


# DEPRECATED: 用 XiaoAnRobotClient 代替，保留至下次 release 后删除（命名规范整改 2026-05）
XiaoAnRobot = XiaoAnRobotClient
