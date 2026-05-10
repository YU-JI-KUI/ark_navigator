import json
import os
from typing import Dict, Any, AsyncIterator

from fastapi.responses import StreamingResponse
from ark_agentic.core.stream import AgentStreamEvent, StreamEventBus
from ark_agentic.core.stream.output_formatter import create_formatter
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel, Field
from ark_nav.core.utils.nav_logger import get_logger
from ark_nav.domains.shouxian.router_schemas import ChatCompletionRequest, SearchIntentRequest, AgentPfmKbRequest
from ark_nav.core.services.xiezhi_http import bootstrap_prompts_from_kb
from ark_nav.core.utils.broadcast_utils import broadcast

logger = get_logger("ark_nav")


class ThresholdUpdateRequest(BaseModel):
    low: float = Field(..., description="Lower energy threshold")
    high: float = Field(..., description="Higher energy threshold ")
    token: str = Field(..., description="Access token")

    @property
    def is_valid(self):
        return self.low < self.high


def create_shouxian_router(intent_agent_handle, shouxian_nav_agent):
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
                    output = await shouxian_nav_agent.process.remote(request)
                    bus.emit_completed(message=json.dumps(output))
                    logger.info(f"{request.msg_id}, 智能体结果: {output}")
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
            response = await shouxian_nav_agent.process.remote(request)
            logger.info(f"{request.msg_id}, 智能体结果: {response}")
            return response

    @router.get("/refresh_prompt")
    async def refresh_root():
        await bootstrap_prompts_from_kb()
        return {
            "xiezhi": os.getenv("XIEZHI_PROMPT"),
            "baize": os.getenv("BAIZE_PROMPT")
        }

    @router.post("/search")
    async def search(request: SearchIntentRequest):
        """
        搜索 API
        """
        result = await shouxian_nav_agent.search.remote(request)
        return result

    @router.post("/reset_faiss_index")
    async def reset_faiss_index(request: AgentPfmKbRequest) -> Dict[str, Any]:
        """重置FAISS INDEX接口。"""
        logger.info("reset SX faiss index")
        broadcast(
            method_name="reset_faiss_index",
            deployment_name="NavAgentDeployment",
            namespace="serve",
            app_name="default",
            request=request
        )
        return {"status": "OK"}

    return router
