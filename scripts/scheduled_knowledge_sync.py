import os
import time
import schedule
from dotenv import load_dotenv
import requests

from ark_nav.core.utils.nav_logger import get_logger, setup_logging

load_dotenv()
setup_logging()
logger = get_logger(__name__)


def knowledge_sync(kg_id, url) -> str:
    try:
        headers = {
            "Content-Type": "application/json; charset=utf-8"
        }

        payload = {
            'kg_id': kg_id,
            'is_reload': True
        }

        response = requests.post(
            url=url, headers=headers, json=payload,
            timeout=int(os.getenv("RAG_EXECUTION_TIMEOUT"), 600))
        response_json = response.json()
        logger.info(response_json)
        if response_json.get("status") == "OK":
            return "success"
        else:
            return "fail"
    except Exception as e:
        logger.error(f"知识库同步异常: {e}", exc_info=True)
        return "fail"


def daily_data_task():
    logger.info("=" * 70)
    logger.info("启动知识库同步任务：从智能体平台更新至本地向量库")
    logger.info("=" * 70)
    local_host = "http://localhost:8080"
    sx_url = f"{local_host}/api/v1/shouxian/reset_faiss_index"
    sx_result = knowledge_sync(kg_id=os.getenv("SHOUXIAN_AGENT_PLATFORM_KG_ID"), url=sx_url)

    ylx_url = f"{local_host}/api/v1/ylx/reset_faiss_index"
    ylx_result = knowledge_sync(kg_id=os.getenv("AGENT_PLATFORM_KG_ID"), url=ylx_url)

    logger.info("=" * 70)
    logger.info(f"结束知识库同步任务，执行状态: 寿险 -> {sx_result}，养老险 -> {ylx_result}")
    logger.info("=" * 70)


def main():
    execution_time = os.getenv("RAG_EXECUTION_TIME")
    # 设置每天 21:30 执行任务
    schedule.every().day.at(execution_time).do(daily_data_task)
    # 保持程序运行
    logger.info(f"定时任务已启动，等待每日{execution_time}执行...")
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次


if __name__ == "__main__":
    main()
