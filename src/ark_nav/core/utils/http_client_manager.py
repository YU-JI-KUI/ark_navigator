import httpx
from typing import Optional, Dict, Any

from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger("ark_nav")


class HttpClientManager:
    """
    httpx.AsyncClient的单例管理器

    注意：
    - 在Ray Serve中，每个deployment进程有独立的单例实例
    - 多个deployment之间的client互不影响
    """
    _instance: Optional['HttpClientManager'] = None
    _client: Optional[httpx.AsyncClient] = None

    def __new__(cls):
        # 单例模式
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self, **kwargs):
        """
        初始化httpx client

        参数:
            **kwargs: httpx.AsyncClient的配置参数

        默认配置:
            - max_keepalive_connections=0（禁用keep-alive，避免陈旧连接）
            - max_connections=100（足够的连接池）
            - timeout=60s, connect=10s（分层超时）
            - http2=False（HTTP/1.1更稳定）
        """
        if self._client is None:
            default_config = {
                'limits': httpx.Limits(
                    max_keepalive_connections=50,
                    max_connections=200,
                    keepalive_expiry=30
                ),
                'timeout': httpx.Timeout(60.0, connect=10.0),
                'http2': False,
                'follow_redirects': True,
            }
            default_config.update(kwargs)
            self._client = httpx.AsyncClient(**default_config)

    async def close(self):
        """关闭并清理client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """获取client实例"""
        if self._client is None:
            logger.warn("HttpClient not initialized. initialize the default one.")
            self.initialize()
        return self._client


# 全局单例（每个进程独立）
_manager = HttpClientManager()


def get_client() -> httpx.AsyncClient:
    """
    获取httpx client实例

    返回:
        httpx.AsyncClient: 已初始化的client

    异常:
        RuntimeError: 如果client未初始化

    示例:
        client = get_client()
        response = await client.post("https://api.com", json=data)
    """
    return _manager.client


def init_client(**kwargs):
    """
    初始化httpx client

    参数:
        **kwargs: httpx.AsyncClient的配置参数

    示例:
        # 使用默认配置
        init_client()

        # 使用预设配置
        from core.client_config import ClientConfig
        init_client(**ClientConfig.HIGH_PERFORMANCE)

        # 完全自定义
        init_client(
            limits=httpx.Limits(max_keepalive_connections=0, max_connections=50),
            timeout=30
        )
    """
    _manager.initialize(**kwargs)


async def close_client():
    """
    关闭并清理client

    注意：通常由装饰器自动调用，无需手动调用
    """
    await _manager.close()
