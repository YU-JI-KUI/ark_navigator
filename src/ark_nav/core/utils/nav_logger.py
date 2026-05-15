"""统一日志模块

设计原则：
1. 基于标准 logging，避免和 Ray / FastAPI / httpx 的日志风格分裂
2. trace_id 通过 ContextVar + LogFilter 自动注入到每条日志
3. 敏感信息通过 LogFilter 自动脱敏，业务代码无感知
4. 提供 print_execution_time 装饰器，统一替代散落的 print() 计时
5. setup_logging 幂等：在每个 Ray Deployment 副本启动时调用都安全
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

from fastapi import Request

from ark_nav.core.services.data_masking_service import mask_text

# ---------------------------------------------------------------------------
# trace_id 上下文
# ---------------------------------------------------------------------------

_trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def set_trace_id(trace_id: Optional[str] = None) -> str:
    """设置当前异步上下文的 trace_id；为空则自动生成 UUID"""
    if not trace_id:
        trace_id = uuid.uuid4().hex
    _trace_id_var.set(trace_id)
    return trace_id


def get_trace_id() -> Optional[str]:
    """获取当前异步上下文的 trace_id；不存在则自动生成"""
    trace_id = _trace_id_var.get()
    if trace_id is None:
        trace_id = set_trace_id()
    return trace_id


# ---------------------------------------------------------------------------
# 日志 Filter：注入 trace_id + 脱敏
# ---------------------------------------------------------------------------


class TraceIdFilter(logging.Filter):
    """把当前上下文的 trace_id 写到 record.trace_id"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _trace_id_var.get() or "-"
        return True


class MaskingFilter(logging.Filter):
    """对 record 的 msg 与 args 做脱敏。

    必须放在 TraceIdFilter 之后（不影响），且优先于 Formatter 执行。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = mask_text(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self._mask_value(v) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(self._mask_value(v) for v in record.args)
        except Exception:
            # 脱敏失败不能影响业务日志输出
            pass
        return True

    @staticmethod
    def _mask_value(value: Any) -> Any:
        if isinstance(value, str):
            return mask_text(value)
        return value


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """结构化 JSON 输出，便于日志采集"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # 把额外字段也带上（logger.info("xxx", extra={...})）
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in (
                "args", "msg", "levelname", "levelno", "name", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "trace_id", "message", "taskName",
            ):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


_TEXT_FORMAT = "%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s - %(message)s"


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

_LOGGING_CONFIGURED = False


def setup_logging(log_level: str = "INFO", log_format: str = "text") -> None:
    """配置全局日志。幂等，重复调用安全。

    Args:
        log_level: DEBUG / INFO / WARNING / ERROR
        log_format: text（开发友好）或 json（生产采集）
    """
    global _LOGGING_CONFIGURED

    level = getattr(logging, log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # 幂等：清掉旧 handler，避免在 Ray Deployment 副本重启或重复 setup 时叠加
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if log_format.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    handler.addFilter(TraceIdFilter())
    handler.addFilter(MaskingFilter())

    root.addHandler(handler)

    _LOGGING_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取标准 logging.Logger。建议传 __name__。"""
    if not _LOGGING_CONFIGURED:
        setup_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# 工具：执行耗时统计装饰器（保持向后兼容）
# ---------------------------------------------------------------------------


def print_execution_time(func: Callable) -> Callable:
    """装饰器：统一打印函数执行耗时。同步/异步均支持。

    历史名称保留以兼容现有调用点；底层走标准 logger，受日志级别和脱敏控制。
    """
    logger = logging.getLogger(func.__module__)

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            cost_ms = (time.perf_counter() - start) * 1000
            logger.info(f"func={func.__name__} cost_ms={cost_ms:.2f}")
            return result
        except Exception:
            cost_ms = (time.perf_counter() - start) * 1000
            logger.exception(f"func={func.__name__} cost_ms={cost_ms:.2f} raised")
            raise

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            cost_ms = (time.perf_counter() - start) * 1000
            logger.info(f"func={func.__name__} cost_ms={cost_ms:.2f}")
            return result
        except Exception:
            cost_ms = (time.perf_counter() - start) * 1000
            logger.exception(f"func={func.__name__} cost_ms={cost_ms:.2f} raised")
            raise

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


# ---------------------------------------------------------------------------
# trace_id 跨 Ray Deployment 透传装饰器
# ---------------------------------------------------------------------------

_TRACE_KW = "_trace_id"


def propagate_trace(func: Callable) -> Callable:
    """装饰 Ray Deployment 的 async 业务方法，实现 trace_id 跨进程透传。

    用法：
        @serve.deployment
        class MyDeployment:
            @propagate_trace
            async def handle(self, request): ...

    调用方在被同样装饰的方法里通过 .remote() 调用时，框架会从 ContextVar 取出
    trace_id 作为隐式 kwarg 注入；被调方在入口 set_trace_id，让该副本的整条
    日志链条都带上同一个 trace_id。
    """

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        trace_id = kwargs.pop(_TRACE_KW, None) or get_trace_id()
        set_trace_id(trace_id)
        return await func(self, *args, **kwargs)

    wrapper.__propagates_trace__ = True  # type: ignore[attr-defined]
    return wrapper


def remote_with_trace(handle_method, *args, **kwargs):
    """对 Ray Serve `handle.method.remote(...)` 的薄封装，自动带上当前 trace_id。

    用法：
        await remote_with_trace(self.intent_agent.classify_intent, request)
    等价于：
        await self.intent_agent.classify_intent.remote(request, _trace_id=get_trace_id())
    """
    kwargs.setdefault(_TRACE_KW, get_trace_id())
    return handle_method.remote(*args, **kwargs)


# ---------------------------------------------------------------------------
# 兼容旧接口（暂保留以避免 import 报错）
# ---------------------------------------------------------------------------


def log_http_request(logger: logging.Logger, request, raw_request) -> None:
    """旧接口；新代码请用 TraceIDMiddleware 自动记录请求"""
    logger.info(
        f"legacy_http_request path={getattr(raw_request.url, 'path', '-')} "
        f"app_key={getattr(request, 'app_key', '-')} "
        f"user_message={getattr(request, 'user_message', '-')}"
    )


def push_to_argilla(push_func: Callable[[dict], Any]):
    """旧接口；保持以兼容 ylx_api_router"""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(request: Any, raw_request: Request):
            response = await func(request, raw_request)
            try:
                intention = response.result if hasattr(response, "result") else response.get("result", "unknown")
                masked_user_message = mask_text(getattr(request, "user_message", "") or "")
                history = (
                    [{"role": msg.role, "text": msg.text} for msg in request.history]
                    if getattr(request, "history", None)
                    else []
                )
                log_entry = {
                    "question": masked_user_message,
                    "intention": intention,
                    "request_id": getattr(request, "request_id", None),
                    "user_id": getattr(request, "user_id", None),
                    "history": history,
                    "session_id": getattr(request, "session_id", None),
                    "timestamp": datetime.now().isoformat(),
                    "metadata": getattr(request, "metadata", None),
                }
                await push_func(log_entry)
            except Exception:
                logging.getLogger(__name__).exception(f"push_to_argilla failed func={func.__name__}")
            return response

        return wrapper

    return decorator
