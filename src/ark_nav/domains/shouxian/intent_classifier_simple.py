import os

from ark_nav.core.services.llm_platform_client import call_bigmodel_api
from ark_nav.core.utils.nav_logger import get_logger

logger = get_logger("ark_nav")

DEFAULT_PROMPT = """你是一个意图分类专家。你需要根据用户提问的'来源'和'问题'，判断其意图。如果意图与平安寿险相关，回答'寿险意图'。如果意图与寿险无关，回答'拒识'。你必须且只可能回答'寿险意图'或'拒识'，不用输出思考过程。

## 输出格式（二选一）：
寿险意图 或者 拒识

#来源：寿险app

#问题：
"""

async def classify_user_intent(
        app_key: str,
        app_secret: str,
        user_message: str,
        prompt_template: str = None
) -> str:
    """
    调用 OpenAI 接口判断用户意图是否属于寿险范畴。

    Args:
        app_key (str): 应用密钥
        app_secret (str): 应用密钥
        user_message (str): 用户最新输入
        prompt_template (str, optional): 自定义提示模板（可选）
    """

    scene_id = os.getenv("SCENE_ID")
    xiezhi_prompt = os.getenv("XIEZHI_PROMPT")

    if not all([app_key, app_secret, user_message]):
        raise ValueError("缺少必要参数: user_message、APP_KEY、APP_SECRET")

    # 构造 prompt
    prompt = xiezhi_prompt or DEFAULT_PROMPT
    query = f"{prompt} {user_message}"
    logger.info(f"意图识别Query: {user_message}")

    try:
        response = await call_bigmodel_api(
            query=query,
            scene_id=scene_id,
            app_key=app_key,
            app_secret=app_secret,
            # 合法输出只有「寿险意图/拒识」几个字；decode 是逐 token 串行的，
            # 限制输出长度掐掉模型偶发多吐字带来的尾延迟
            max_tokens=10,
        )

        result = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        logger.info(f"模型返回:{result}")

        # 提取结果
        if "寿险意图" in result:
            return "寿险意图"
        elif "拒识" in result:
            return "拒识"
        else:
            logger.error("result is not 寿险意图 or 拒识，默认返回拒识")
            return "寿险意图"

    except Exception as e:
        logger.error(f"请求异常:{str(e)}", exc_info=True)
        return "拒识"


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()
    result = asyncio.run(classify_user_intent(
            app_key=os.getenv("APP_KEY"),
            app_secret=os.getenv("APP_SECRET"),
            user_message="我想体检"
    ))

    print(result)
