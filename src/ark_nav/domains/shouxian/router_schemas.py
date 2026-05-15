from dataclasses import dataclass
from typing import Any, Dict, List, Optional,Literal
from pydantic import BaseModel, Field


@dataclass
class Message:
    """消息数据类"""
    role: str  # user, ai, system
    text: str
    timestamp: Optional[str] = None


@dataclass
class IntentResult:
    """意图识别结果"""
    result: str
    source: str = "direct"  # direct(直接识别) 或 rewritten(重写后识别)
    extra: Optional[Dict[str, Any]] = None

class IntentRequest(BaseModel):
    app_key: str
    app_secret: str
    user_message: str
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    history: Optional[List[Message]] = []
    energe_base: Optional[bool] = False
    return_details: Optional[bool] = False
    reject_reconfirm: Optional[bool] = False
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="其他元数据")

# 搜索目前没有多轮对话
class SearchIntentRequest(BaseModel):
    message: str = ""
    msg_id: Optional[str] = None
    request_id: Optional[str] = None
    user_id: Optional[str] = None
    reject_reconfirm: Optional[bool] = False

# 定义ChatCompletionRequest类
class ChatCompletionRequest(BaseModel):
    message: str = ""
    timestamp: Optional[str] = None
    system_id: Optional[str] = None
    contexts: Optional[list] = []
    msg_type: Optional[str] = None
    buChannel: Optional[dict] = {}
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    agent_conversation_id: Optional[str] = None
    card_params: Optional[dict] = {}
    to_agent: Optional[str] = ""
    extrainfo: Optional[dict] = {}
    msg_id: Optional[str] = None
    stream: Optional[bool] = False
    stream_protocol: Literal["agui", "internal", "enterprise", "alone"] = Field(
        default="enterprise", description="流式协议 AGUI")

# 定义ChatCompletionResponse类
class ChatCompletionResponse(BaseModel):
    bu_type: str = "shouxian"
    source_bu_type: str = ""
    service_type: str = ""
    is_chat: str = "0"
    timestamp: str = ""
    code: str = ""
    code_msg: str = ""
    card_content: dict = {}
    to_agent: str = ""
    agent_conversation_id: str = ""
    openId: str = ""
    sa_business_type: str = ""
    sa_business_data: str = ""
