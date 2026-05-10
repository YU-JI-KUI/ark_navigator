from fastapi import APIRouter
import os
import json
from typing import Dict, Any, AsyncIterator
from fastapi.responses import StreamingResponse
from ark_agentic.core.stream import AgentStreamEvent, StreamEventBus
from ark_agentic.core.stream.output_formatter import create_formatter
import asyncio
from ark_nav.core.utils.broadcast_utils import broadcast
from ark_nav.core.utils.nav_logger import get_logger
from ark_nav.core.services.xiezhi_http import bootstrap_prompts_from_kb
from ark_nav.domains.yanglaoxian.router_schemas import YLXRequest, AgentPfmKbRequest

logger = get_logger("ark_nav")


def create_router(agent_handler):
    router = APIRouter(prefix="/api/v1/ylx", tags=["YLX"])

    @router.get("/refresh")
    async def refresh():
        await bootstrap_prompts_from_kb()
        return {
            "ylx": os.getenv("YLX_PROMPT")
        }

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
                    output = await agent_handler.run.remote(request)
                    bus.emit_completed(message=json.dumps(output.to_dict()))
                    logger.info(f"{request.msg_id}, 智能体结果: {output.to_dict()}")
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
            response = await agent_handler.run.remote(request)
            logger.info(f"{request.msg_id}, 智能体结果: {response.to_dict()}")
            return response

    @router.post("/reset_faiss_index")
    async def reset_faiss_index(request: AgentPfmKbRequest) -> Dict[str, Any]:
        """重置FAISS INDEX接口。"""
        logger.info("reset YLX faiss index")
        broadcast(
            method_name="reset_faiss_index",
            deployment_name="NavAgentDeployment",
            namespace="serve",
            app_name="default",
            request=request
        )
        return {"status": "OK"}

    return router
