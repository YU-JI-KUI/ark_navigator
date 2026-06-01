import json
import datetime
from dataclasses import fields
import os
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv()
from ark_nav.domains.yanglaoxian.router_schemas import OneKeyResult, XiaoAnRobotRequests, OneKeyLLMResult, KnowledgeInfo
from ark_nav.core.services.llm_platform_client import call_bigmodel_api
from ark_nav.core.services.knowledge_base import KnowledgeBase
from ark_nav.core.utils.http_client_manager import get_client
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time
from ark_nav.domains.yanglaoxian.prompts import ONEKEY_INTENT_CLASSIFIER

logger = get_logger("ark_nav_OneKey")


@print_execution_time
async def classify_user_intent(
        msg_id: str,
        scene_id: str,
        app_key: str,
        app_secret: str,
        user_message: str,
        knowledge_base: KnowledgeBase,
) -> OneKeyLLMResult:
    """
    调用大模型 API 判断用户意图。

    Args:
        msg_id: 消息 id
        scene_id: 大模型场景 id
        app_key: 应用 key
        app_secret: 应用 secret
        user_message: 用户最新输入
        knowledge_base: 知识库抽象，模式由全局配置决定
    """
    if not all([app_key, app_secret, user_message]):
        raise ValueError("缺少必要参数: user_message、APP_KEY、APP_SECRET")
    system_message = await knowledge_base.fetch_faq_answer(query="养老险一键到底意图识别") or ONEKEY_INTENT_CLASSIFIER

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
        response = await call_bigmodel_api(
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


class XiaoAnRobot:
    """
    小安机器人
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
    knowledge_base_file = "ylx_onekey_knowledge_base.xlsx"

    def __init__(self, knowledge_base: KnowledgeBase, t: float = 0.85):
        self.t = t
        self.robot = XiaoAnRobot()
        self.scene_id = os.getenv("INTENT_REWRITE_SCENE_ID")
        self.app_key = os.getenv("INTENT_REWRITE_APP_KEY")
        self.app_secret = os.getenv("INTENT_REWRITE_APP_SECRET")
        self.knowledge_base = knowledge_base

    @print_execution_time
    async def get_onekey_result(self, msg_id: str, llm_result: OneKeyLLMResult, card_content) -> OneKeyResult:
        knowledge = await self.knowledge_base.fetch_table_knowledge(
            query=llm_result.sub_intent, score_threshold=self.t,
        )
        logger.info(f"{msg_id}, 查询知识table: {knowledge}")

        if knowledge is None:
            logger.info(f"{msg_id}, 【非一键场景 - 无知识库配置】")
            return OneKeyResult(card_content=card_content)
        elif llm_result.task_type == OneKeyLLMResult.TASK_TYPE_INFO and card_content.get("answerType", "") == XiaoAnRobot.MENU_ITEMS:
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
                app_secret=self.app_secret, user_message=message, knowledge_base=self.knowledge_base)
            if llm_result.domain == "其他" or llm_result.sub_intent == "其他":
                return OneKeyResult(card_content=data)
            else:
                result = await self.get_onekey_result(msg_id=msg_id, llm_result=llm_result, card_content=data)
                return result
        else:
            return OneKeyResult(card_content=data)

    @print_execution_time
    async def call_xiaoan_only(self, msg_id: str, message: str, user_id: str) -> OneKeyResult:
        """只调小安机器人，不走一键编排（不做 LLM 二次识别、不查 Table 知识库）。

        返回小安机器人的原始 data 作为 card_content，结果 source 保持 "ylXian"。
        用于 YLXRequest.is_onekey_enabled = False 的场景。
        """
        payload = XiaoAnRobotRequests(
            repository_id=int(os.getenv("XIAOAN_REPOSITORY_ID")),
            question=message,
            user_id=user_id,
            label=["app", "好福利"]
        ).to_dict()
        data = await self.robot.chat(msg_id=msg_id, params=payload)
        return OneKeyResult(card_content=data)
