"""寿险意图相关的领域常量与枚举（领域共享单一来源）。

整改时间：2026-05（命名规范第一轮）
原因：原本 IntentType 在 intent_classifier_advanced.py 与 intent_classifier_cot.py
中重复定义了两份完全相同的 Enum，是 bug 温床（一旦其中一份改了枚举值就会
出现"两个类对意图的理解不一致"的潜在问题）。统一抽到此文件单一定义。
"""
from enum import Enum


class IntentType(Enum):
    """意图类型枚举（注意：value 是 RAG / LLM 接口的契约文本，改动需同步）"""
    LIFE_INSURANCE = "寿险意图"  # 寿险相关意图
    REJECTED = "拒识"  # 无法识别的意图
