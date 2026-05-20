"""HTTP 入口中间件：trace_id 注入 + 请求/响应统一日志"""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ark_nav.core.services.data_masking_service import mask_text
from ark_nav.core.utils.nav_logger import get_logger, set_trace_id

logger = get_logger(__name__)

_MAX_BODY_LOG_BYTES = 8 * 1024  # 单个请求/响应 body 最多打印 8KB，超出截断
_TRACE_HEADER = "X-Request-ID"

# 静默路径：基础设施探活 / 文档静态资源，不打日志、不读 body、不解析 response
# trace_id 仍然设置并写入响应头，业务逻辑该跑跑
_QUIET_PATHS: frozenset[str] = frozenset({
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/favicon.ico",
})

# 这些 HTTP 方法没有请求体，无需读 body、无需打 payload
_METHODS_WITHOUT_BODY: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})


def _safe_decode(body: bytes) -> str:
    if not body:
        return ""
    truncated = len(body) > _MAX_BODY_LOG_BYTES
    snippet = body[:_MAX_BODY_LOG_BYTES].decode("utf-8", errors="replace")
    if truncated:
        snippet += f"...[truncated {len(body) - _MAX_BODY_LOG_BYTES} bytes]"
    return snippet


def _format_body(raw: bytes) -> Any:
    """尝试 JSON 解析；失败则返回原文片段"""
    text = _safe_decode(raw)
    if not text:
        return None
    masked = mask_text(text)
    try:
        return json.loads(masked)
    except (ValueError, TypeError):
        return masked


class TraceIDMiddleware(BaseHTTPMiddleware):
    """统一处理 trace_id 与请求日志。

    - 从 `X-Request-ID` 取 trace_id；缺失则自动生成
    - 设置到 ContextVar，整条异步链路自动携带
    - 在响应头回写 trace_id
    - 自动打印 request_in / request_out 日志，含 path / payload / status / cost / response
    """

    async def dispatch(self, request: Request, call_next):
        trace_id = set_trace_id(request.headers.get(_TRACE_HEADER))

        # 静默路径：仅设置 trace_id 与响应头，不打日志、不读 body、不抓 response
        if request.url.path in _QUIET_PATHS:
            response = await call_next(request)
            response.headers[_TRACE_HEADER] = trace_id
            return response

        # 仅对可能携带 body 的方法读取请求体并打 payload
        has_body = request.method not in _METHODS_WITHOUT_BODY
        body_bytes = b""
        if has_body:
            body_bytes = await request.body()

            async def _replay_receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request._receive = _replay_receive  # type: ignore[attr-defined]

        start = time.perf_counter()
        if has_body:
            logger.info(
                f"request_in method={request.method} path={request.url.path} "
                f"payload={_format_body(body_bytes)}"
            )
        else:
            logger.info(f"request_in method={request.method} path={request.url.path}")

        status_code = 500
        response_body = b""
        try:
            response: Response = await call_next(request)
            status_code = response.status_code

            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            response_body = b"".join(chunks)

            new_response = Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
            new_response.headers[_TRACE_HEADER] = trace_id
            return new_response
        finally:
            cost_ms = (time.perf_counter() - start) * 1000
            logger.info(
                f"request_out method={request.method} path={request.url.path} "
                f"status={status_code} cost_ms={cost_ms:.2f} "
                f"response={_format_body(response_body)}"
            )
