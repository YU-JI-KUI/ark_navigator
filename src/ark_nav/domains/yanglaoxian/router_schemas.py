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

    @property
    def is_onekey_enabled(self) -> bool:
        """是否启用养老险一键场景。

        默认 True（向后兼容老客户端）。客户端可通过 extrainfo.ylx_onekey_enabled
        显式关闭，关闭后仅调小安机器人返回原始结果，不走一键编排。

        取值约定（大小写不敏感）：
        - 不传 / 字段缺失 / None → True（默认开启）
        - bool True / "true" / "yes" / "1" → True
        - bool False / "false" / "no" / "0" → False
        - 其他无法识别的值 → True（默认开启，保守）
        """
        if not self.extrainfo:
            return True
        raw = self.extrainfo.get("ylx_onekey_enabled")
        if raw is None:
            return True
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() not in ("false", "no", "0")
        if isinstance(raw, (int, float)):
            return bool(raw)
        return True


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
