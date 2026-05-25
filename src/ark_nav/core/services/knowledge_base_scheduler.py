"""知识库每日同步调度器（进程内 asyncio 实现）

每个 Ray Deployment 副本各自创建一个调度器实例，按配置时间（默认 21:30）
自动调用 knowledge_base.reload()。

设计要点：
- 失败不抛出：调度循环不会因单次 reload 失败而终止
- 幂等启动：重复调用 start_async() 只生效一次
- 远程模式安全：RemoteRestKnowledgeBase.reload() 是 no-op，调度器照样工作
- 副本可识别：每条日志带 replica_tag / pid / kb_id，便于多副本调试
- 活性可证：长睡分段执行，每小时打一条心跳日志
- async 启动：从 Deployment 的 async 上下文里调用 start_async()，确保跑在 actor 的真实 event loop 上
"""
from __future__ import annotations

import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional

from ark_nav.config import settings
from ark_nav.core.services.knowledge_base import KnowledgeBase
from ark_nav.core.utils.nav_logger import get_logger, set_trace_id

logger = get_logger(__name__)

# 心跳间隔（秒）。把长睡拆成多段，每段结束打一条心跳日志证明调度器活着。
_HEARTBEAT_INTERVAL_S = 3600  # 每小时
# 心跳的最小剩余时间阈值：剩余等待时间小于该值不打心跳（避免触发前 1 秒还来一条）
_HEARTBEAT_MIN_REMAINING_S = 60
# 副本错峰窗口（秒）：定时器触发时再随机延迟 0~该值，把所有副本的 reload 散列到一个窗口内
# 避免 N 个副本同时挤少数 GPU 副本导致排队长尾
_JITTER_WINDOW_S = 600  # 10 分钟


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


def _compute_next_run(hour: int, minute: int, *, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def _try_get_replica_tag() -> str:
    """尽力获取 Ray Serve 副本 id，拿不到就返回 'unknown'。

    Ray 的内部 API 跨版本不稳定，所以包一层 try。
    """
    try:
        from ray.serve.context import _get_internal_replica_context  # type: ignore
        ctx = _get_internal_replica_context()
        if ctx is not None:
            # Ray Serve 不同版本字段名可能是 replica_id / replica_tag
            return getattr(ctx, "replica_id", None) \
                or getattr(ctx, "replica_tag", None) \
                or "unknown"
    except Exception:
        pass
    return "unknown"


class KnowledgeBaseSyncScheduler:
    """每日按固定时间触发 KnowledgeBase.reload() 的进程内调度器"""

    def __init__(self, knowledge_base: KnowledgeBase, sync_time: Optional[str] = None):
        self._knowledge_base = knowledge_base
        self._sync_time = sync_time or settings.kb_sync_time
        self._task: Optional[asyncio.Task] = None

        # 副本身份标识（用于日志区分多副本）
        self._replica_tag = _try_get_replica_tag()
        self._pid = os.getpid()
        self._kb_id = hex(id(knowledge_base))

    def _tag(self) -> str:
        """每条日志统一前缀，让多副本可区分"""
        return (
            f"domain={self._knowledge_base.domain} "
            f"replica={self._replica_tag} "
            f"pid={self._pid} "
            f"kb_id={self._kb_id}"
        )

    async def start_async(self) -> None:
        """异步启动调度器。

        必须从 Deployment 的 async 方法（或异步 hook）里调用，确保 task 跑在
        actor 真正使用的 event loop 上。重复调用安全。
        """
        if self._task is not None and not self._task.done():
            logger.info(f"scheduler.start_async skipped (already running) {self._tag()}")
            return

        try:
            hour, minute = _parse_hhmm(self._sync_time)
        except ValueError:
            logger.exception(f"scheduler.start_async failed (bad sync_time) {self._tag()}")
            return

        next_run_at = _compute_next_run(hour, minute)
        # 用 asyncio.create_task —— 此时一定在 running loop 中
        self._task = asyncio.create_task(self._run_forever(hour, minute))

        logger.info(
            f"scheduler.started {self._tag()} "
            f"sync_time={hour:02d}:{minute:02d} "
            f"next_run_at={next_run_at.isoformat(timespec='seconds')}"
        )

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info(f"scheduler.stopped {self._tag()}")
        self._task = None

    async def trigger_now(self) -> None:
        """立即触发一次 reload（不影响定时循环）。供运维或调试使用。"""
        logger.info(f"scheduler.manual_trigger {self._tag()}")
        await self._do_reload(planned_at=None)

    async def _run_forever(self, hour: int, minute: int) -> None:
        """主循环：等到指定时间 → 触发 reload → 计算下次 → 继续等"""
        while True:
            next_run_at = _compute_next_run(hour, minute)
            try:
                await self._sleep_until(next_run_at)
            except asyncio.CancelledError:
                logger.info(f"scheduler.cancelled {self._tag()}")
                return

            await self._do_reload(planned_at=next_run_at)

    async def _sleep_until(self, next_run_at: datetime) -> None:
        """分段睡眠到目标时间，每段结束打一条心跳日志"""
        while True:
            remaining = (next_run_at - datetime.now()).total_seconds()
            if remaining <= 0:
                return
            chunk = min(remaining, float(_HEARTBEAT_INTERVAL_S))
            await asyncio.sleep(chunk)

            remaining_after = (next_run_at - datetime.now()).total_seconds()
            if remaining_after > _HEARTBEAT_MIN_REMAINING_S:
                logger.info(
                    f"scheduler.heartbeat {self._tag()} "
                    f"remaining_seconds={remaining_after:.0f} "
                    f"next_run_at={next_run_at.isoformat(timespec='seconds')}"
                )

    async def _do_reload(self, *, planned_at: Optional[datetime]) -> None:
        """触发一次 reload，包含完整生命周期日志。

        - 每次 reload 生成独立 trace_id，避免继承"触发懒启动的请求"的 trace
          （否则 scheduler 后台任务的日志会永远挂在第一个请求的 trace 上）
        - 定时触发时引入随机抖动 0~_JITTER_WINDOW_S 秒，把多副本的 reload 散到一个窗口内
          手动触发（trigger_now，planned_at=None）跳过抖动，立即执行
        """
        # 为本次 reload 分配独立 trace_id；后续 logger 和 remote_with_trace 都会带上它
        reload_trace_id = f"kb-reload-{uuid.uuid4().hex[:12]}"
        set_trace_id(reload_trace_id)

        planned_str = planned_at.isoformat(timespec='seconds') if planned_at else "manual"

        # 定时触发的错峰抖动（手动触发不抖）
        if planned_at is not None and _JITTER_WINDOW_S > 0:
            jitter_s = random.uniform(0, _JITTER_WINDOW_S)
            logger.info(
                f"scheduler.jitter {self._tag()} "
                f"planned_at={planned_str} jitter_seconds={jitter_s:.1f}"
            )
            try:
                await asyncio.sleep(jitter_s)
            except asyncio.CancelledError:
                logger.info(f"scheduler.cancelled_during_jitter {self._tag()}")
                return

        logger.info(f"scheduler.triggered {self._tag()} planned_at={planned_str}")

        start_ts = datetime.now()
        success = False
        error_msg: Optional[str] = None
        try:
            await self._knowledge_base.reload()
            success = True
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.exception(f"scheduler.failed {self._tag()}")
        finally:
            cost_ms = (datetime.now() - start_ts).total_seconds() * 1000
            if success:
                logger.info(
                    f"scheduler.completed {self._tag()} "
                    f"cost_ms={cost_ms:.1f} success=true"
                )
            else:
                logger.warning(
                    f"scheduler.completed {self._tag()} "
                    f"cost_ms={cost_ms:.1f} success=false error={error_msg}"
                )
