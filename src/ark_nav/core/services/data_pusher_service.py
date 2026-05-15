import asyncio
import logging

import httpx

_logger = logging.getLogger(__name__)


class DataPusherService:
    """数据推送服务"""

    def __init__(self, url: str, batch_size: int = 1000, flush_interval: int = 60, channel: str = None):
        self.url = url
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue = None
        self.task = None
        self.channel = channel

    async def initialize(self):
        self.queue = asyncio.Queue()
        self.task = asyncio.create_task(self._background_task())

    async def _background_task(self):
        while True:
            batch = []
            while len(batch) < self.batch_size:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                    batch.append(item)
                except asyncio.TimeoutError:
                    break
            if batch:
                await self._send_batch(batch)

    async def _send_batch(self, batch):
        payload = {"logs": batch, "channel": self.channel}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, json=payload)
                _logger.info("已推送 %d 条数据到Argilla, 状态码: %s", len(batch), response.status_code)
            except Exception:
                _logger.exception("推送失败")

    async def push(self, data):
        if self.queue is None:
            await self.initialize()
        await self.queue.put(data)
