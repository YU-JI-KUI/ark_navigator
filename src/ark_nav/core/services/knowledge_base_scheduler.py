"""知识库每日同步调度器（进程内 asyncio 实现）

每个 Ray Deployment 副本启动时各自创建一个调度器实例，按配置时间
（默认 09:30）自动调用 knowledge_base.reload()。

设计要点：
- 失败不抛出：调度循环不会因单次 reload 失败而终止
- 幂等启动：重复调用 start() 只生效一次
- 远程模式安全：RemoteRestKnowledgeBase.reload() 是 no-op，调度器照样工作
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from ark_nav.config import settings
from ark_nav.core.services.knowledge_base import KnowledgeBase
from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh_str, mm_str = value.strip().split(":", 1)
        hour = int(hh_str)
        minute = int(mm_str)
    except (ValueError, AttributeError) as e:
        raise ValueError(f"非法的 kb_sync_time 配置: {value!r}，应为 HH:MM 格式") from e
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"kb_sync_time 超出取值范围: {value!r}")
    return hour, minute


def _seconds_until_next(hour: int, minute: int, *, now: Optional[datetime] = None) -> float:
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


class KnowledgeBaseSyncScheduler:
    """每日按固定时间触发 KnowledgeBase.reload() 的进程内调度器"""

    def __init__(self, knowledge_base: KnowledgeBase, sync_time: Optional[str] = None):
        self._knowledge_base = knowledge_base
        self._sync_time = sync_time or settings.kb_sync_time
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """启动调度。重复调用 idempotent。"""
        if self._task is not None and not self._task.done():
            return
        try:
            hour, minute = _parse_hhmm(self._sync_time)
        except ValueError:
            logger.exception(f"KnowledgeBaseSyncScheduler 启动失败 domain={self._knowledge_base.domain}")
            return

        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_forever(hour, minute))
        logger.info(
            f"KnowledgeBaseSyncScheduler started domain={self._knowledge_base.domain} "
            f"sync_time={hour:02d}:{minute:02d}"
        )

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _run_forever(self, hour: int, minute: int) -> None:
        while True:
            wait_s = _seconds_until_next(hour, minute)
            logger.debug(
                f"KnowledgeBaseSyncScheduler domain={self._knowledge_base.domain} "
                f"sleep_seconds={wait_s:.1f}"
            )
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                return

            try:
                await self._knowledge_base.reload()
            except Exception:
                logger.exception(
                    f"KnowledgeBaseSyncScheduler reload failed domain={self._knowledge_base.domain}"
                )
