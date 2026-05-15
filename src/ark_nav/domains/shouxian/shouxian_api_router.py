import json
import os
from typing import AsyncIterator

from fastapi.responses import StreamingResponse
from ark_agentic.core.stream import AgentStreamEvent, StreamEventBus
from ark_agentic.core.stream.output_formatter import create_formatter
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel, Field
from ark_nav.core.utils.nav_logger import get_logger, remote_with_trace
from ark_nav.domains.shouxian.router_schemas import ChatCompletionRequest, SearchIntentRequest
from ark_nav.core.services.xiezhi_http import init_prompt_from_agent_rag

logger = get_logger("ark_nav")


class ThresholdUpdateRequest(BaseModel):
    low: float = Field(..., description="Lower energy threshold")
    high: float = Field(..., description="Higher energy threshold ")
    token: str = Field(..., description="Access token")

    @property
    def is_valid(self):
        return self.low < self.high


def create_shouxian_router(shouxian_nav_agent):
    """创建寿险意图识别路由 - 注入依赖"""
    router = APIRouter(prefix="/api/v1/shouxian", tags=["Shouxian"])

    @router.post("/nav_agent")
    async def nav_agent(request: ChatCompletionRequest):
        """
        快捷服务聚合 API，替代之前的画布智能体
        """
        if request.stream:
            queue: asyncio.Queue[AgentStreamEvent] = asyncio.Queue()
            done_event = asyncio.Event()
            bus = StreamEventBus(run_id=request.msg_id, session_id=request.session_id, queue=queue)
            formatter = create_formatter(
                request.stream_protocol,
                source_bu_type="shouxian",
                app_type="jgj",
            )

            async def run_agent() -> None:
                try:
                    bus.emit_created("收到您的消息，正在处理中...")
                    bus.on_thinking_delta(delta="正在调用寿险红利接口....")
                    output = await remote_with_trace(shouxian_nav_agent.process, request)
                    bus.emit_completed(message=json.dumps(output))
                    logger.info(f"nav_agent stream done msg_id={request.msg_id}")
                finally:
                    done_event.set()

            async def event_stream() -> AsyncIterator[str]:
                task = asyncio.create_task(run_agent())
                try:
                    while True:
                        if done_event.is_set() and queue.empty():
                            break
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=0.1)
                            sse_line = formatter.format(event)
                            if sse_line is not None:
                                yield sse_line
                        except asyncio.TimeoutError:
                            continue
                finally:
                    if not task.done():
                        task.cancel()

            return StreamingResponse(event_stream(), media_type="text/event-stream")
        else:
            response = await remote_with_trace(shouxian_nav_agent.process, request)
            logger.info(f"nav_agent done msg_id={request.msg_id}")
            return response

    @router.get("/refresh_prompt")
    async def refresh_root():
        await init_prompt_from_agent_rag()
        return {
            "xiezhi": os.getenv("XIEZHI_PROMPT"),
            "baize": os.getenv("BAIZE_PROMPT")
        }

    @router.post("/search")
    async def search(request: SearchIntentRequest):
        """
        搜索 API
        """
        result = await remote_with_trace(shouxian_nav_agent.search, request)
        return result

    return router
