"""知识库同步调度器（进程内 asyncio 双循环）

为每个 Ray Deployment 副本提供两套同步策略：
- 全量循环：每天 21:30 ± 抖动；reload(faq_labels=None)
- 增量循环：每 N 分钟 ± 抖动；reload(faq_labels=["hotfix"])

设计要点：
- 双循环互斥：用 asyncio.Lock 保证全量和增量不会同时跑（避免 dense_index 竞争）
- 失败不抛出：单次失败不影响下次
- 副本可识别：日志含 domain / kg_id / replica_tag / pid（不再用对象内存地址）
- trace_id 区分：full → kb-full-xxx，partial → kb-partial-xxx
- 抖动错峰：全量 ±_FULL_JITTER_S，增量 ±_PARTIAL_JITTER_S
"""
from __future__ import annotations

import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from ark_nav.config import settings
from ark_nav.core.services.knowledge_base import KnowledgeBase
from ark_nav.core.utils.nav_logger import get_logger, set_trace_id

logger = get_logger(__name__)

# 心跳间隔（秒）。把长睡拆成多段，每段结束打一条心跳日志证明调度器活着
_HEARTBEAT_INTERVAL_S = 21600  # 6 小时（频率高了日志会刷屏）
# 心跳的最小剩余时间阈值：剩余等待时间小于该值不打心跳（避免触发前 1 秒还来一条）
_HEARTBEAT_MIN_REMAINING_S = 60
# 全量同步错峰窗口（秒）：避免 N 副本同时挤 GPU
_FULL_JITTER_S = 600  # 10 分钟
# 增量同步错峰窗口（秒）：30 分钟间隔下，错峰不能太大否则两次会重叠
_PARTIAL_JITTER_S = 180  # 3 分钟
# 增量循环启动延迟（秒）：避免和首次全量重叠
_PARTIAL_INITIAL_DELAY_S = 60


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh_str, mm_str = value.strip().split(":", 1)
        hour = int(hh_str)
        minute = int(mm_str)
    except (ValueError, AttributeError) as e:
        raise ValueError(f"非法的 sync_time 配置: {value!r}，应为 HH:MM 格式") from e
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"sync_time 超出取值范围: {value!r}")
    return hour, minute


def _compute_next_run(hour: int, minute: int, *, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def _try_get_replica_tag() -> str:
    """尽力获取 Ray Serve 副本 id，拿不到就返回 'unknown'。"""
    try:
        from ray.serve.context import _get_internal_replica_context  # type: ignore
        ctx = _get_internal_replica_context()
        if ctx is not None:
            return getattr(ctx, "replica_id", None) \
                or getattr(ctx, "replica_tag", None) \
                or "unknown"
    except Exception:
        pass
    return "unknown"


class KnowledgeBaseSyncScheduler:
    """支持全量 + 增量双策略的进程内同步调度器"""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        full_sync_time: Optional[str] = None,
        partial_interval_minutes: Optional[int] = None,
        partial_faq_labels: Optional[List[str]] = None,
    ):
        self._kb = knowledge_base
        self._full_sync_time = full_sync_time or settings.kb_full_sync_time_effective
        self._partial_interval_s = (
            (partial_interval_minutes or settings.kb_partial_sync_interval_minutes) * 60
        )
        self._partial_labels = list(partial_faq_labels or settings.kb_partial_faq_labels_list)

        # 防止全量和增量同时跑（dense_index 竞争）
        self._reload_lock = asyncio.Lock()

        # 两个独立循环 task
        self._full_task: Optional[asyncio.Task] = None
        self._partial_task: Optional[asyncio.Task] = None

        # 副本身份标识
        self._replica_tag = _try_get_replica_tag()
        self._pid = os.getpid()

    def _tag(self) -> str:
        """每条日志统一前缀，让多副本可区分。

        kg_id 来自业务知识库配置（AGENT_PLATFORM_KG_ID 等），不再用 Python 对象内存地址
        """
        return (
            f"domain={self._kb.domain} "
            f"kg_id={getattr(self._kb, 'kg_id', None)} "
            f"replica={self._replica_tag} "
            f"pid={self._pid}"
        )

    async def start_async(self) -> None:
        """启动两个循环。必须在 actor 的 async 上下文里调用。重复调用安全。"""
        if self._full_task is not None or self._partial_task is not None:
            logger.info(f"scheduler.start_async skipped (already running) {self._tag()}")
            return

        # 解析全量时间，失败则放弃启动
        try:
            hour, minute = _parse_hhmm(self._full_sync_time)
        except ValueError:
            logger.exception(f"scheduler.start_async failed (bad full_sync_time) {self._tag()}")
            return

        if not self._partial_labels:
            logger.warning(
                f"scheduler.start_async partial labels 为空，增量同步将被跳过 {self._tag()}"
            )

        next_full_at = _compute_next_run(hour, minute)
        self._full_task = asyncio.create_task(self._full_loop(hour, minute))
        self._partial_task = asyncio.create_task(self._partial_loop())

        logger.info(
            f"scheduler.started {self._tag()} "
            f"full_sync_time={hour:02d}:{minute:02d} "
            f"next_full_at={next_full_at.isoformat(timespec='seconds')} "
            f"partial_interval_minutes={self._partial_interval_s // 60} "
            f"partial_labels={self._partial_labels}"
        )

    def stop(self) -> None:
        for task_attr in ("_full_task", "_partial_task"):
            task = getattr(self, task_attr)
            if task and not task.done():
                task.cancel()
            setattr(self, task_attr, None)
        logger.info(f"scheduler.stopped {self._tag()}")

    async def trigger_now(self, faq_labels: Optional[List[str]] = None) -> None:
        """手动触发一次 reload。供运维或调试使用。

        Args:
            faq_labels: None 触发全量；非空触发增量
        """
        full = not faq_labels
        logger.info(f"scheduler.manual_trigger {self._tag()} full={full} labels={faq_labels}")
        async with self._reload_lock:
            await self._do_reload(full=full, planned_at=None, labels=faq_labels)

    # ------------------------------------------------------------
    # 全量循环
    # ------------------------------------------------------------

    async def _full_loop(self, hour: int, minute: int) -> None:
        while True:
            next_run_at = _compute_next_run(hour, minute)
            try:
                await self._sleep_until_with_heartbeat(next_run_at, label="full")
            except asyncio.CancelledError:
                logger.info(f"scheduler.full_cancelled {self._tag()}")
                return

            # 全量抖动
            if _FULL_JITTER_S > 0:
                jitter_s = random.uniform(0, _FULL_JITTER_S)
                logger.info(
                    f"scheduler.full_jitter {self._tag()} jitter_seconds={jitter_s:.1f}"
                )
                try:
                    await asyncio.sleep(jitter_s)
                except asyncio.CancelledError:
                    return

            async with self._reload_lock:
                await self._do_reload(full=True, planned_at=next_run_at, labels=None)

    # ------------------------------------------------------------
    # 增量循环
    # ------------------------------------------------------------

    async def _partial_loop(self) -> None:
        if not self._partial_labels:
            return  # 标签为空时跳过整个循环

        # 启动延迟，避免和首次全量挤一起
        try:
            await asyncio.sleep(_PARTIAL_INITIAL_DELAY_S)
        except asyncio.CancelledError:
            return

        while True:
            jitter = random.uniform(0, _PARTIAL_JITTER_S)
            wait_s = self._partial_interval_s + jitter
            try:
                await asyncio.sleep(wait_s)
            except asyncio.CancelledError:
                logger.info(f"scheduler.partial_cancelled {self._tag()}")
                return

            async with self._reload_lock:
                await self._do_reload(
                    full=False, planned_at=datetime.now(), labels=self._partial_labels
                )

    # ------------------------------------------------------------
    # 公共部分
    # ------------------------------------------------------------

    async def _sleep_until_with_heartbeat(self, next_run_at: datetime, *, label: str) -> None:
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
                    f"scheduler.heartbeat {self._tag()} loop={label} "
                    f"remaining_seconds={remaining_after:.0f} "
                    f"next_run_at={next_run_at.isoformat(timespec='seconds')}"
                )

    async def _do_reload(
        self,
        *,
        full: bool,
        planned_at: Optional[datetime],
        labels: Optional[List[str]],
    ) -> None:
        """执行一次 reload，包含完整生命周期日志。

        必须在持有 self._reload_lock 的情况下调用。
        """
        mode = "full" if full else "partial"
        trace_id = f"kb-{mode}-{uuid.uuid4().hex[:12]}"
        set_trace_id(trace_id)

        planned_str = planned_at.isoformat(timespec='seconds') if planned_at else "manual"
        logger.info(
            f"scheduler.triggered {self._tag()} mode={mode} labels={labels} "
            f"planned_at={planned_str}"
        )

        start_ts = datetime.now()
        success = False
        error_msg: Optional[str] = None
        try:
            await self._kb.reload(faq_labels=labels)
            success = True
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.exception(f"scheduler.failed {self._tag()} mode={mode}")
        finally:
            cost_ms = (datetime.now() - start_ts).total_seconds() * 1000
            if success:
                logger.info(
                    f"scheduler.completed {self._tag()} mode={mode} "
                    f"cost_ms={cost_ms:.1f} success=true"
                )
            else:
                logger.warning(
                    f"scheduler.completed {self._tag()} mode={mode} "
                    f"cost_ms={cost_ms:.1f} success=false error={error_msg}"
                )
