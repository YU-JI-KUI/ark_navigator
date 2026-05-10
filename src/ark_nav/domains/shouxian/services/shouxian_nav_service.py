"""向后兼容薄壳：保留旧 import 路径，实现已搬至 ./shouxian/ 子包（2026-05 整改）。

外部唯一调用方：domains/shouxian/agents/nav_agent.py:10
    from ark_nav.domains.shouxian.services.shouxian_nav_service import ShouXianNavService

实现拆分到：
    shouxian/_history_utils.py    — 工具函数 + LIFE_INSURANCE / REJECTION 常量
    shouxian/bonus_chat_agent.py  — BonusChatAgent（红利渠道 HTTP + token 缓存）
    shouxian/intent_recognition.py — IntentRecognitionService
    shouxian/classify_service.py   — ClassifyService
    shouxian/rag_service.py        — RagService
    shouxian/nav_service.py        — ShouXianNavService 主编排器

详见 src/ark_nav/docs/MODULE_MAP.md。
"""
from dotenv import load_dotenv

load_dotenv()  # 保留 import 时副作用，与原 shouxian_nav_service.py 行为一致

# 公开 API（外部仅 nav_agent.py 使用 ShouXianNavService）
from ark_nav.domains.shouxian.services.shouxian.nav_service import ShouXianNavService

__all__ = [
    "ShouXianNavService",
]
