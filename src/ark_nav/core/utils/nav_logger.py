"""日志配置 - 与 Ray Serve 协同工作

设计原则：
1. 使用 Python logging，与 Ray 日志系统兼容
2. 只记录业务逻辑日志，不重复 Ray 已有的（HTTP请求、耗时等）
3. 按需结构化输出（JSON），默认关闭，便于解析
4. 使用 Ray 的 request_id 作为 trace_id

2026-05 整改：新增三项能力
- msg_id 自动注入（与 trace_id 同构）：业务代码无需手动 f-string 拼接
- 敏感信息自动脱敏（手机/身份证/邮箱/银行卡/地址 5 类正则 + 敏感字段名 [REDACTED]）
- 灰度回滚：环境变量 LOG_MASK_ENABLED=0 可关闭脱敏
"""

import asyncio
import logging
import os
import uuid
from contextvars import ContextVar

import structlog
from typing import Optional
import time
from functools import wraps

from ark_nav.core.utils.masking_rules import (
    DEFAULT_PATTERN_DEFS,
    REDACTED_PLACEHOLDER,
    is_sensitive_key,
)

_trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)
_msg_id_var: ContextVar[Optional[str]] = ContextVar('msg_id', default=None)


def _add_trace_id_processor(logger, method_name, event_dict):
    """Structlog 处理器：自动添加 trace_id 到日志

    此函数在模块级别定义，确保 structlog 正确引用
    """
    trace_id = get_trace_id()
    if trace_id:
        event_dict['trace_id'] = trace_id
    return event_dict


def _add_msg_id_processor(logger, method_name, event_dict):
    """Structlog 处理器：自动添加 msg_id 到日志（2026-05 新增）。

    msg_id 由 TraceIDMiddleware 或 @with_log_context 装饰器在请求入口
    set_msg_id() 写入 ContextVar。本 processor 自动读取注入到结构化字段。

    与 trace_id 一样，使用 ContextVar 跨 await 边界自动传播。
    跨 Ray Deployment 边界（actor 进程）需在 deployment 入口手动 set_msg_id()。
    """
    msg_id = _msg_id_var.get()
    if msg_id and 'msg_id' not in event_dict:
        event_dict['msg_id'] = msg_id
    return event_dict


def _mask_sensitive_processor(logger, method_name, event_dict):
    """Structlog 处理器：自动脱敏敏感信息（2026-05 新增）。

    两层处理：
    1. 字段名匹配：key 在 SENSITIVE_FIELD_KEYS 中（如 password、app_secret）
       → 整个 value 替换为 [REDACTED]
    2. 字符串值脱敏：所有 str 类型的 value（含 event 文本）通过 5 类正则
       → 手机号、身份证、邮箱、银行卡、地址自动打码

    通过环境变量 LOG_MASK_ENABLED=0 可关闭（灰度回滚用）。
    规则定义在 ark_nav.core.utils.masking_rules 单一来源。
    """
    if os.getenv("LOG_MASK_ENABLED", "1") != "1":
        return event_dict

    for key in list(event_dict.keys()):
        value = event_dict[key]

        # 第 1 层：敏感字段名 → 整体 [REDACTED]（不论 value 类型）
        if is_sensitive_key(key):
            event_dict[key] = REDACTED_PLACEHOLDER
            continue

        # 第 2 层：字符串 value → 应用脱敏正则
        if isinstance(value, str):
            masked = value
            for _, pattern, repl_func in DEFAULT_PATTERN_DEFS:
                masked = pattern.sub(repl_func, masked)
            event_dict[key] = masked

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
    # 顺序很重要：先注入上下文字段（trace_id/msg_id），再脱敏，最后渲染。
    # 脱敏 processor 必须在 Renderer 之前才能影响最终输出。
    processors = [
        _add_trace_id_processor,
        _add_msg_id_processor,
        _mask_sensitive_processor,
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


def set_msg_id(msg_id: Optional[str]) -> Optional[str]:
    """设置当前请求的 msg_id（2026-05 新增）。

    与 trace_id 同构：在请求入口（HTTP 中间件 / Ray Deployment 入口）调用一次，
    下游所有日志通过 _add_msg_id_processor 自动注入 msg_id 字段。

    Args:
        msg_id: 业务消息 ID（来自 ChatCompletionRequest.msg_id 等）。
                None 或空串时不写入（保留原有值）。

    Returns:
        实际写入 ContextVar 的值（如未写入则返回 None）。

    Example:
        # 在 deployment 入口
        async def process(self, request):
            set_msg_id(request.msg_id)
            ...
    """
    if msg_id:
        _msg_id_var.set(msg_id)
        return msg_id
    return None


def get_msg_id() -> Optional[str]:
    """获取当前请求的 msg_id

    Returns:
        msg_id 或 None（如果未设置）
    """
    return _msg_id_var.get()


def with_log_context(*, msg_id_attr: str = "msg_id", trace_id_attr: str = "trace_id"):
    """装饰器：自动从方法第一个参数提取 msg_id / trace_id 写入 ContextVar。

    解决 Ray Serve 跨 actor 边界 ContextVar 不自动传播的问题：
    每个 Deployment 入口方法用此装饰器后，下游所有日志自动带上 msg_id / trace_id。

    Args:
        msg_id_attr: 从参数对象读取 msg_id 的属性名（默认 "msg_id"）。
        trace_id_attr: 从参数对象读取 trace_id 的属性名（默认 "trace_id"）。

    支持以下三种调用形式（自动识别）：
        @with_log_context()
        async def process(self, request):  # request.msg_id 自动提取
            ...

        @with_log_context()
        async def handle(self, query, msg_id=None):  # 关键字参数 msg_id
            ...

        @with_log_context(msg_id_attr="request_id")
        async def custom(self, req):  # 自定义属性名
            ...

    注意：
    - 仅装饰 async 方法（Ray Serve 入口都是 async）
    - 第一参数（self 之后）若是 pydantic BaseModel，按属性名提取
    - 也会扫描 kwargs 里同名的键
    - 提取失败（None / AttributeError）时静默跳过，不影响业务

    Example:
        from ark_nav.core.utils.nav_logger import with_log_context

        class NavAgentDeployment:
            @with_log_context()
            async def process(self, request: ChatCompletionRequest):
                # 此处所有 logger.info(...) 自动带 msg_id 字段
                ...
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 尝试从第 2 参数（args[1]，跳过 self）提取
            target = args[1] if len(args) >= 2 else None

            # 提取 msg_id
            msg_id = None
            if target is not None:
                msg_id = getattr(target, msg_id_attr, None)
            if not msg_id:
                msg_id = kwargs.get(msg_id_attr)
            if msg_id:
                set_msg_id(msg_id)

            # 提取 trace_id
            trace_id = None
            if target is not None:
                trace_id = getattr(target, trace_id_attr, None)
            if not trace_id:
                trace_id = kwargs.get(trace_id_attr)
            if trace_id:
                set_trace_id(trace_id)

            return await func(*args, **kwargs)

        return async_wrapper

    return decorator


def log_http_request(logger: logging.Logger, request, raw_request):
    """[DEPRECATED 2026-05] 手写的 HTTP 请求头/体脱敏日志。

    历史背景：在引入 _mask_sensitive_processor 之前，这是项目唯一的脱敏
    机制——硬编码识别 "secret" / "authorization" 等关键字。

    现状：
    - 全项目零调用方（搬到此函数从未被引用过）
    - 新机制（_mask_sensitive_processor + SENSITIVE_FIELD_KEYS）已自动覆盖
      headers / body / 字段名脱敏

    不要使用此函数；如需打印请求详情，直接：
        logger.info("request", request=request, raw_request=raw_request)
    敏感字段（app_secret 等）会被 _mask_sensitive_processor 自动 [REDACTED]。

    保留此函数仅为兼容性，预计阶段 6 与其他死代码一并清理。
    """
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
