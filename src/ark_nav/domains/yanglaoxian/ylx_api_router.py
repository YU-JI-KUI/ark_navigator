from fastapi import APIRouter, Request
import os
import json
from typing import AsyncIterator
from fastapi.responses import StreamingResponse
from ark_agentic.core.stream import AgentStreamEvent, StreamEventBus
from ark_agentic.core.stream.output_formatter import create_formatter
import asyncio
from ark_nav.core.utils.nav_logger import get_logger, remote_with_trace
from ark_nav.core.services.agent_platform_client import init_prompt_from_agent_rag
from ark_nav.domains.shouxian.router_schemas import IntentRequest, IntentResult
from ark_nav.domains.yanglaoxian.router_schemas import YLXRequest

logger = get_logger("ark_nav")


def create_router(agent_handler):
    router = APIRouter(prefix="/api/v1/ylx", tags=["YLX"])

    @router.get("/refresh")
    async def refresh():
        await init_prompt_from_agent_rag()
        return {
            "ylx": os.getenv("YLX_PROMPT")
        }

    @router.post("/classify")
    async def classify(request: IntentRequest, raw_request: Request) -> IntentResult:
        """
        接收 app_key、app_secret 和 user_message，返回意图分类结果。
        打印请求头和请求体日志。
        """
        result = await remote_with_trace(agent_handler.process, request.user_message, request.history)
        return result

    @router.post("/navi")
    async def navi(request: YLXRequest):
        """
        接收 app_key、app_secret 和 user_message，返回意图分类结果。
        打印请求头和请求体日志。
        """
        logger.info("calling YLX navi endpoint")
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
                    output = await remote_with_trace(agent_handler.run, request)
                    bus.emit_completed(message=json.dumps(output.to_dict()))
                    logger.info(f"ylx agent stream done msg_id={request.msg_id}")
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
            response = await remote_with_trace(agent_handler.run, request)
            logger.info(f"ylx agent done msg_id={request.msg_id}")
            return response

    return router
