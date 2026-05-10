"""平安大模型平台配置（环境变量映射）。

历史命名：原类名 LLMPlfConfig（Plf = Platform 缩写），可读性差。
2026-05 命名规范第一轮整改：重命名为 LLMPlatformConfig，旧名保留为 alias，
预计下次 release 后删除（约 1 个迭代周期）。
"""
import os


class LLMPlatformConfig:

    OPEN_AI_URL = os.getenv("OPEN_AI_URL")
    RSA_PK = os.getenv("RSA_PK")
    CRE_ID = os.getenv("CRE_ID")
    OPEN_API_CODE = os.getenv("OPEN_API_CODE")
    # 养老险模型配置
    YLX_LLM_APP_KEY = os.getenv("YLX_LLM_APP_KEY")
    YLX_LLM_APP_SECRET = os.getenv("YLX_LLM_APP_SECRET")
    YLX_LLM_SCENE_ID = os.getenv("YLX_LLM_SCENE_ID")

    @classmethod
    def check_required(cls):
        required = ["OPEN_AI_URL",
                     "RSA_PK",
                     "CRE_ID",
                     "OPEN_API_CODE",
                     "YLX_LLM_APP_KEY",
                     "YLX_LLM_APP_SECRET",
                     "YLX_LLM_SCENE_ID"]
        missing = [k for k in required if not getattr(cls, k)]
        if missing:
            raise ValueError(f"Missing required env vars: {missing}")


# DEPRECATED: 用 LLMPlatformConfig 代替，保留至下次 release 后删除（命名规范整改 2026-05）
LLMPlfConfig = LLMPlatformConfig
