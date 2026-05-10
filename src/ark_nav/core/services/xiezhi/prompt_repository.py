"""智能体平台 Prompt 拉取与缓存。

从 xiezhi_http.py 拆分而来（2026-05），保持原函数签名与逻辑一字不改。

注意：init_prompt_from_agent_rag 通过写入 os.environ 的方式
"动态注入" XIEZHI_PROMPT / BAIZE_PROMPT / YLX_PROMPT 三个环境变量，
下游业务代码通过 os.getenv 读取（详见 docs/ENV_INVENTORY.md C 类隐藏配置）。
"""
import os

from ark_nav.core.services.xiezhi.kb_client import search_kb
from ark_nav.core.utils.agent_platform_config import AgentPfmConfig
from ark_nav.core.utils.nav_logger import get_logger, print_execution_time

logger = get_logger(__name__)


@print_execution_time
async def init_prompt_from_agent_rag():
    """
    调用智能体画布平台，查询提示词。
    """
    logger.info("start loading ARK prompts")
    xiezhi_prompt = await _get_prompt_by_name("服务意图识别")
    baize_prompt = await _get_prompt_by_name("白泽意图重写")
    ylx_prompt = await _get_prompt_by_name("养老险意图识别")
    if xiezhi_prompt:
        os.environ["XIEZHI_PROMPT"] = xiezhi_prompt
        logger.info("load prompt for (服务意图识别) successfully!")
    if baize_prompt:
        os.environ["BAIZE_PROMPT"] = baize_prompt
        logger.info("load prompt for (白泽意图重写) successfully!")
    if ylx_prompt:
        os.environ["YLX_PROMPT"] = ylx_prompt
        logger.info("load prompt for (养老险意图识别) successfully!")


async def _get_prompt_by_name(prompt_name: str) -> str | None:
    logger.info(f"Calling agent model to get prompt templete")
    try:
        agent_platform_kg_id = AgentPfmConfig.KG_ID
        answers = await search_kb(
            query=prompt_name,
            kb_type=["faq"],
            kb_ids=[agent_platform_kg_id]
        )
        if answers is not None and len(answers) > 0:
            return answers[0].get("answer")
        logger.warning(f"fail to load any prompt from kb by: {prompt_name}")
        return None
    except Exception as e:
        logger.error(f"调用 prompt 服务失败: {e}", exc_info=True)
        return None
