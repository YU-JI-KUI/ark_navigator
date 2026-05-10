"""日志配置 - 与 Ray Serve 协同工作

设计原则：
1. 使用 Python logging，与 Ray 日志系统兼容
2. 只记录业务逻辑日志，不重复 Ray 已有的（HTTP请求、耗时等）
3. 按需结构化输出（JSON），默认关闭，便于解析
4. 使用 Ray 的 request_id 作为 trace_id
"""

import asyncio
import logging
import uuid
from contextvars import ContextVar

import structlog
from typing import Optional
import time
from functools import wraps

_trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def _add_trace_id_processor(logger, method_name, event_dict):
    """Structlog 处理器：自动添加 trace_id 到日志

    此函数在模块级别定义，确保 structlog 正确引用
    """
    trace_id = get_trace_id()
    if trace_id:
        event_dict['trace_id'] = trace_id
    return event_dict


def setup_logging(log_level: str = "INFO", log_format: str = "text"):
    """配置日志系统

    Args:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_format: 输出格式 (json/text)
    """

    # 设置日志级别
    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除现有的 handlers（避免重复）
    root_logger.handlers.clear()

    # 配置 Python logging（Ray 会自动收集）
    logging.basicConfig(
        format="%(name)s - %(levelname)s  - %(message)s",
    )

    # 配置 structlog 处理器
    processors = [
        _add_trace_id_processor,
        # structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # 根据格式选择渲染器
    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        # text 格式（开发友好）
        processors.append(structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=30,
            sort_keys=False,
        ))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """获取 logger 实例

    Args:
        name: logger 名称（通常使用 __name__）

    Returns:
        配置好的 logger

    Example:
        logger = get_logger(__name__)
        logger.info("业务事件", user_id=123, action="购买")
    """
    return structlog.get_logger(name)


def set_trace_id(trace_id: Optional[str] = None) -> str:
    """设置当前请求的 trace_id

    Args:
        trace_id: 自定义 trace_id，如果为 None 则自动生成

    Returns:
        设置的 trace_id

    Example:
        # 从 HTTP 头获取或自动生成
        trace_id = set_trace_id(request.headers.get('X-Request-ID'))

        # 自动生成
        trace_id = set_trace_id()
    """
    if trace_id is None:
        trace_id = str(uuid.uuid4())
    _trace_id_var.set(trace_id)
    return trace_id


def get_trace_id() -> Optional[str]:
    """获取当前请求的 trace_id

    Returns:
        trace_id 或 None（如果未设置）

    Example:
        trace_id = get_trace_id()
        logger.info("处理请求", trace_id=trace_id)
    """
    trace_id = _trace_id_var.get()
    if trace_id is None:
        trace_id=set_trace_id()
    return trace_id


def log_http_request(logger: logging.Logger, request, raw_request):
    logger.info("=== 请求头 (Headers) ===")
    for key, value in raw_request.headers.items():
        # 敏感字段如 Authorization、app_secret 可选隐藏
        if "secret" in key.lower() or "authorization" in key.lower():
            logger.info(f"{key}: [REDACTED]")
        else:
            logger.info(f"{key}: {value}")

    # === 2、打印请求体 (Body) ===
    logger.info("=== 请求体 (Body) ===")
    logger.info(f"app_key: {request.app_key}")
    logger.info(f"app_secret: [REDACTED]")  # 敏感信息隐藏
    logger.info(f"user_message: {request.user_message}")


_exec_time_logger = structlog.get_logger("ark_nav.exec_time")


def print_execution_time(func):
    """
    装饰器：同时支持同步和异步函数，准确打印执行耗时
    """

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            end = time.perf_counter()
            _exec_time_logger.info(f"[INFO] {func.__name__} 执行耗时: {end - start:.4f} 秒, params: {kwargs}")
            return result
        except Exception as e:
            end = time.perf_counter()
            _exec_time_logger.error(f"[ERROR] {func.__name__} 执行异常，耗时: {end - start:.4f} 秒, params: {kwargs}")
            raise e

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start = asyncio.get_running_loop().time()
        try:
            result = await func(*args, **kwargs)
            end = asyncio.get_running_loop().time()
            _exec_time_logger.info(f"[INFO] {func.__name__} 异步执行耗时: {end - start:.4f} 秒, params: {kwargs}")
            return result
        except Exception as e:
            end = asyncio.get_running_loop().time()
            _exec_time_logger.error(f"[ERROR] {func.__name__} 异步执行异常，耗时: {end - start:.4f} 秒, params: {kwargs}")
            raise e

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper
