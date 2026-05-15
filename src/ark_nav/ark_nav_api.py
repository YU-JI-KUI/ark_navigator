"""FastAPI HTTP入口"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from ray import serve
from fastapi.openapi.docs import get_swagger_ui_html

from ark_nav.core.utils.nav_logger import get_logger, setup_logging
from ark_nav.core.utils.trace_id_middleware import TraceIDMiddleware

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 3))

app = FastAPI(
    title="万能服务-Ark-Navigator",
    description="基于Ray Serve的高并发AI智能体应用",
    version="0.1.0"
)

app.add_middleware(TraceIDMiddleware)

logger = get_logger(__name__)


@serve.deployment(
    name="ark-navigator-fastapi",
    num_replicas=MIN_REPLICAS,
    max_ongoing_requests=100,
    ray_actor_options={
        "num_cpus": 0.5,
    }
)
@serve.ingress(app)
class APIDeployment:
    """FastAPI HTTP入口"""

    def __init__(self,
                 shouxian_nav_agent_handle,
                 ylx_intent_agent_handle):
        load_dotenv()
        setup_logging()
        self.shouxian_nav_agent = shouxian_nav_agent_handle
        self.ylx_intent_agent = ylx_intent_agent_handle

        if self.shouxian_nav_agent:
            self.register_shouxian_routers()
            logger.info("[shouxian] API服务注册完成")

        if self.ylx_intent_agent:
            self.register_ylx_routers()
            logger.info("[ylx] API服务注册完成")

        logger.info("[ARK API] ALL HTTP服务初始化完成")

    @app.get("/")
    async def root(self):
        return {
            "service": "ark-navigator",
            "version": "0.2.0",
            "docs": "/docs"
        }

    @app.get("/health")
    async def health(self):
        return {"status": "healthy"}

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_html(self):
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js",
            swagger_css_url="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css",
        )

    def register_shouxian_routers(self):
        from ark_nav.domains.shouxian import shouxian_api_router
        shouxian_router = shouxian_api_router.create_shouxian_router(self.shouxian_nav_agent)
        app.include_router(shouxian_router)

    def register_ylx_routers(self):
        from ark_nav.domains.yanglaoxian import ylx_api_router
        ylx_router = ylx_api_router.create_router(self.ylx_intent_agent)
        app.include_router(ylx_router)
