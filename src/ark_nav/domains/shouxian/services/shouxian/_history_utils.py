"""寿险导航服务 - 工具函数与常量。

从 shouxian_nav_service.py 拆分而来（2026-05），保持原函数签名与逻辑一字不改。

包含：
- 业务常量：LIFE_INSURANCE, REJECTION
- 卡片解析：_extract_by_path, _extract_card_content, _content_to_text
- 历史消息处理：process_history
- RAG 答案解析：_parse_rag_answer
"""
import copy
import re
from typing import Any, Dict, List, Optional, Union


LIFE_INSURANCE = "寿险意图"
REJECTION = "拒识"


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
