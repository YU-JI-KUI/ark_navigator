from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Literal


@dataclass
class OneKeyResult:
    """一键到底输出参"""
    card_content: Dict[str, Any]
    service_type: str = None
    code: str = "0"
    code_msg: str = ""
    source_bu_type: str = "ylXian"
    source: str = "ylXian"


@dataclass
class XiaoAnRobotRequests:
    """小安机器人入参"""
    repository_id: Optional[int]  # 170 stg, 16 prod
    question: str
    user_id: str
    media_type: str = "text"
    access_entrance: str = ""
    label: Optional[List[str]] = field(default_factory=list)

    def to_dict(self):
        return {
            "repositoryId": self.repository_id,
            "question": self.question,
            "userId": self.user_id,
            "mediaType": self.media_type,
            "accessEntrance": self.access_entrance,
            "label": self.label
        }


@dataclass
class OneKeyLLMResult:
    """一键大模型意图识别出参"""
    domain: str = field(default="")
    sub_intent: str = field(default="")
    task_type: str = field(default="")
    confidence: float = field(default=0.0)

    TASK_TYPE_INFO = "Info"
    TASK_TYPE_NAVI = "Navigation"
    TASK_TYPE_ACTION = "Action"


@dataclass
class KnowledgeInfo:
    """知识库信息对象"""
    category_o: str
    sub_category_o: str
    category_i: str
    sub_category_i: str
    query: str
    type: str
    answer: str
    title: str
    sub_title: str
    button: str
    link_key: str
    link: str


@dataclass
class YLXRequest:
    """养老险小导航入参"""
    session_id: str | None = None
    msg_id: str | None = None
    user_id: str | None = None
    system_id: str | None = None
    buChannel: Dict[str, Any] | None = None
    message: str = ""
    msg_type: str | None = None
    card_params: Dict[str, Any] | None = None
    extrainfo: Dict[str, Any] | None = None
    stream: Optional[bool] = False
    stream_protocol: Literal["agui", "internal", "enterprise", "alone"] = field(default="enterprise")


@dataclass
class YLXResponse:
    """养老险小导航出参"""
    code: str
    code_msg: str
    source_bu_type: str
    card_content: Dict[str, Any]
    card_type: str
    service_type: str
    extrainfo: Dict[str, Any]

    def to_dict(self):
        return {
            "code": self.code,
            "code_msg": self.code_msg,
            "source_bu_type": self.source_bu_type,
            "card_content": self.card_content,
            "card_type": self.card_type,
            "service_type": self.service_type,
            "extrainfo": self.extrainfo
        }
