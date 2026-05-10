"""Ray Serve应用入口"""

from dotenv import load_dotenv, dotenv_values

load_dotenv()
import ray
from ray import serve

from ark_nav.core.models import (
    RAGModelDeployment
)

from ark_nav.ark_nav_api import APIDeployment
from ark_nav.domains.shouxian import (
    NavAgentDeployment,
    IntentClassifierDeployment,
    ShouxianBertDeployment
)
from ark_nav.domains.yanglaoxian import (
    NavYLXAgentDeployment
)

from ark_nav.config import settings

import os

from ark_nav.core.utils.nav_logger import setup_logging, get_logger

os.environ["HF_HUB_OFFLINE"] = '1'
os.environ["TRANSFORMERS_OFFLINE"] = '1'
os.environ["HF_DATASETS_OFFLINE"] = '1'
os.environ["HF_HUB_DISABLE_TELEMETRY"] = '1'

setup_logging(
    log_level=settings.log_level,
    log_format=settings.log_format
)

logger = get_logger(__name__)


def build_app(args=None):
    """构建Ray Serve应用"""

    logger.info("=" * 60)
    logger.info("构建Ray Serve应用")
    logger.info("=" * 60)

    # 1. 模型层（GPU单副本）
    rag_models = RAGModelDeployment.bind()
    shouxian_bert = ShouxianBertDeployment.bind()

    # 2. Agent层（CPU多副本自动扩展）
    shouxian_intent_agent = IntentClassifierDeployment.bind(rag_models, shouxian_bert)
    shouxian_nav_agent = NavAgentDeployment.bind(rag_models, shouxian_intent_agent)
    ylx_intent_agent = NavYLXAgentDeployment.bind(rag_models)

    # 4. API入口
    app = APIDeployment.bind(
        shouxian_nav_agent,
        shouxian_intent_agent,
        ylx_intent_agent,
    )

    logger.info("=" * 60)
    logger.info("应用构建完成")
    logger.info("=" * 60)

    return app


def main():
    """主入口: 启动Ray Serve应用"""

    # 启动Ray（如果还没启动）
    if not ray.is_initialized():
        ray.init(address="auto", include_dashboard=True, log_to_driver=True,
                 runtime_env={"env_vars": dotenv_values(".env")})
    # 启动Serve（配置HTTP选项）
    serve.start(
        http_options={
            "host": "0.0.0.0",
            "port": settings.port,
        }
    )

    # 部署应用
    serve.run(build_app())

    logger.info("\n" + "=" * 70)
    logger.info("\U0001f680 服务已启动")
    logger.info("=" * 70)
    logger.info(f"\U0001f4e1 API服务:       http://localhost:{settings.port}")
    logger.info(f"\U0001f4da API文档:       http://localhost:{settings.port}/docs")
    logger.info(f"\U0001f4ca Ray Dashboard: http://localhost:8265")
    logger.info("=" * 70)
    logger.info("\n\U0001f4a1 Dashboard功能:")
    logger.info("  - 查看所有部署状态和副本数")
    logger.info("  - 监控请求QPS、延迟、错误率")
    logger.info("  - 查看GPU/CPU使用率")
    logger.info("  - 实时日志和追踪")
    logger.info("  - 自动扩展状态")
    logger.info("\n按Ctrl+C停止服务\n")

    # 保持运行
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n服务停止")


if __name__ == "__main__":
    main()
