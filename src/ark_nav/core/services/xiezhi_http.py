"""向后兼容薄壳：保留旧 import 路径，实现已搬至 ./xiezhi/ 子包（2026-05 整改）。

外部调用方继续按原路径 import（旧名仍可用，作为 alias 保留至下次 release）：
    from ark_nav.core.services.xiezhi_http import call_llm  # 原 call_bigmodel_api
    from ark_nav.core.services.xiezhi_http import bootstrap_prompts_from_kb  # 原 init_prompt_from_agent_rag
    from ark_nav.core.services.xiezhi_http import fetch_rag

实现拆分到：
    xiezhi/llm_client.py        — call_llm
    xiezhi/kb_client.py         — search_kb, fetch_rag, extract_answer, _get_faq_*_data 等
    xiezhi/prompt_repository.py — bootstrap_prompts_from_kb, _get_prompt_by_name
    xiezhi/auth.py              — _get_agent_auth_token

详见 src/ark_nav/docs/MODULE_MAP.md。
"""
from dotenv import load_dotenv

load_dotenv()  # 保留 import 时副作用，与原 xiezhi_http.py 行为一致

# 公开 API（被项目内多个文件 import）
from ark_nav.core.services.xiezhi.llm_client import (
    call_llm,
    call_bigmodel_api,  # DEPRECATED alias，兼容下次 release
)
from ark_nav.core.services.xiezhi.kb_client import (
    search_kb,
    extract_answer,
    fetch_rag,
    # 注意：以下两个函数原本是私有 (_xxx 前缀)，但 agent_pfm_kb_service.py
    # 直接 import 了它们。整改阶段保持原契约不变，故仍从此处 re-export。
    # 后续若想让它们真正变私有，需先改 agent_pfm_kb_service 的 import 路径。
    _get_faq_page_data,
    _get_faq_table_data,
)
from ark_nav.core.services.xiezhi.prompt_repository import (
    bootstrap_prompts_from_kb,
    init_prompt_from_agent_rag,  # DEPRECATED alias，兼容下次 release
)

# 防御性导出：原 xiezhi_http.py 的全部公开符号
__all__ = [
    "call_llm",
    "call_bigmodel_api",  # DEPRECATED alias
    "fetch_rag",
    "bootstrap_prompts_from_kb",
    "init_prompt_from_agent_rag",  # DEPRECATED alias
    "search_kb",
    "extract_answer",
    "_get_faq_page_data",
    "_get_faq_table_data",
]


def main():
    """调试入口（保持与原文件一致），手动运行可拉取 FAQ Table 数据查看示例。"""
    import asyncio
    from ark_nav.core.services.xiezhi.kb_client import _get_faq_table_data
    from ark_nav.core.utils.agent_platform_config import AgentPlatformConfig
    from ark_nav.core.utils.nav_logger import get_logger

    logger = get_logger(__name__)
    result = asyncio.run(_get_faq_table_data(AgentPlatformConfig.KG_ID))
    logger.info(f"=========={len(result)}==========")
    for item in result[:5]:  # 仅展示前5条作为示例
        logger.info(item)


if __name__ == '__main__':
    main()
