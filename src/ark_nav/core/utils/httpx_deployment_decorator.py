from functools import wraps

import asyncio
import os

from ark_nav.core.utils.http_client_manager import init_client, close_client


def with_http_client(client_config: dict = None):
    """
    装饰器：自动为Ray Serve deployment初始化和清理httpx client

    用法：
        # 方式1：使用默认配置
        @serve.deployment
        @with_http_client()
        class MyDeployment:
            pass

        # 方式2：完全自定义
        @serve.deployment
        @with_http_client(client_config={
            'limits': httpx.Limits(max_keepalive_connections=0, max_connections=100),
            'timeout': 60,
        })
        class CustomDeployment:
            pass

    参数：
        client_config: httpx.AsyncClient配置字典，不传则使用环境变量CLIENT_SCENARIO

    注意：
        - 装饰器顺序：@serve.deployment在上，@with_http_client()在下
        - 每个deployment独立配置，互不影响
        - 使用get_client()获取client实例
    """

    def decorator(cls):
        original_init = cls.__init__
        original_del = getattr(cls, '__del__', None)

        @wraps(original_init)
        def new_init(self, *args, **kwargs):
            # 获取配置

            config = client_config if client_config else {}
            init_client(**config)
            original_init(self, *args, **kwargs)

        def new_del(self):
            # 清理资源
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(close_client())
            except:
                pass

            # 调用原始__del__（如果有）
            if original_del:
                original_del(self)

        cls.__init__ = new_init
        cls.__del__ = new_del

        return cls

    return decorator
