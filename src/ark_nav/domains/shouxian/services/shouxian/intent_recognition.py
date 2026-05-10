"""寿险意图识别 - 寿险中控调用编排。

从 shouxian_nav_service.py 拆分而来（2026-05），保持原 class 行为一字不改。

负责：
- 调用 BonusChatClient.submit_business_request 走寿险中控
- 后处理：cross-bu 检查 + to_agent 重置（生存金/理赔报案场景）
"""
from typing import Any, Dict

from ark_nav.domains.shouxian.services.shouxian.bonus_chat_client import BonusChatClient


class IntentRecognitionService:
    rejection_card_type_list = []

    def __init__(self):
        self.bonus_chat_client = BonusChatClient()

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
        response = await self.bonus_chat_client.submit_business_request(msg_id=req_id, params=request_body)
        return self._postprocess(response, to_agent, bu_channel)
