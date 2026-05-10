import os


class LLMPlfConfig:

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
