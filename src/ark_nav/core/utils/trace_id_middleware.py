"""FastAPI 中间件 - 统一处理请求上下文"""
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ark_nav.core.utils.nav_logger import set_trace_id, set_msg_id, get_logger

logger = get_logger(__name__)


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Trace ID 中间件

    自动处理：
    1. 从请求头 X-Request-ID 获取 trace_id
    2. 如果没有，自动生成 UUID
    3. 注入到响应头 X-Request-ID
    4. 设置到 contextvars（自动传递到异步调用链）

    2026-05 整改：
    - 增加从 X-Msg-Id 请求头读取 msg_id（如果客户端按 header 传）。
    - 注：业务请求体里的 msg_id 字段不在中间件层提取（避免 body 消费问题），
      由 @with_log_context 装饰器在 router/deployment 入口提取。
    """

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        # 从请求头获取或自动生成 trace_id
        trace_id = request.headers.get('X-Request-ID')
        logger.info(f"X-Request-ID: {trace_id}")
        trace_id = set_trace_id(trace_id)
        logger.info(f"trace_id: {trace_id}")

        # 从请求头读取 msg_id（可选，业务体里的 msg_id 由下游装饰器处理）
        header_msg_id = request.headers.get('X-Msg-Id')
        if header_msg_id:
            set_msg_id(header_msg_id)

        logger.info(f"[INGRESS START] path={request.url.path}, trace_id={trace_id}, ts={start}")
        # 处理请求
        response: Response = await call_next(request)

        end = time.time()
        logger.info(f"[INGRESS END] path={request.url.path}, trace_id={trace_id}, latency={end - start:.3f}s")

        # 添加到响应头
        response.headers['X-Request-ID'] = trace_id

        return response
