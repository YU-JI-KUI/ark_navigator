"""智能体平台配置（环境变量映射）。

历史命名：原类名 AgentPfmConfig（Pfm = Platform 缩写），可读性差。
2026-05 命名规范第一轮整改：重命名为 AgentPlatformConfig，旧名保留为 alias，
预计下次 release 后删除（约 1 个迭代周期）。
"""
import os


class AgentPlatformConfig:
    HOST = os.getenv("AGENT_PLATFORM_HOST")
    TOKEN_URL = os.getenv("AGENT_PLATFORM_TOKEN_URL")
    RAG_QUERY_URL = os.getenv("AGENT_PLATFORM_RAG_QUERY_URL")
    KG_ID = os.getenv("AGENT_PLATFORM_KG_ID")
    TENANT_ID = os.getenv("AGENT_PLATFORM_APP_ID")
    APP_SEC = os.getenv("AGENT_PLATFORM_APP_SECRET")
    RAG_FAQ_PAGE_URL = os.getenv("AGENT_PLATFORM_RAG_FAQ_PAGE_URL")
    RAG_FAQ_PAGE_SIMILAR_URL = os.getenv("AGENT_PLATFORM_RAG_FAQ_PAGE_SIMILAR_URL")
    RAG_FAQ_TABLE_LIST_URL = os.getenv("AGENT_PLATFORM_RAG_FAQ_TABLE_LIST_URL")
    RAG_FAQ_TABLE_DETAIL_URL = os.getenv("AGENT_PLATFORM_RAG_FAQ_TABLE_DETAIL_URL")

    @classmethod
    def check_required(cls):
        required = ["AGENT_PLATFORM_HOST", "AGENT_PLATFORM_TOKEN_URL", "AGENT_PLATFORM_RAG_QUERY_URL",
                     "AGENT_PLATFORM_KG_ID", "AGENT_PLATFORM_APP_ID", "AGENT_PLATFORM_APP_SECRET",
                     "AGENT_PLATFORM_RAG_FAQ_PAGE_URL", "AGENT_PLATFORM_RAG_FAQ_PAGE_SIMILAR_URL",
                     "AGENT_PLATFORM_RAG_FAQ_TABLE_LIST_URL", "AGENT_PLATFORM_RAG_FAQ_TABLE_DETAIL_URL"]
        missing = [k for k in required if not getattr(cls, k)]
        if missing:
            raise ValueError(f"Missing required env vars: {missing}")


# DEPRECATED: 用 AgentPlatformConfig 代替，保留至下次 release 后删除（命名规范整改 2026-05）
AgentPfmConfig = AgentPlatformConfig
