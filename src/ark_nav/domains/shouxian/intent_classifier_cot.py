"""
意图识别服务--COT版本
1. 基于当前的通用规则 + COT数据进行过滤
2. 根据用户问题，去找到最相关的COT数据作为few shot
3. 调用BOB的模型进行判断
"""

import asyncio
import json
import os
from typing import List, Dict, Any, Optional,Tuple
from enum import Enum
import pandas as pd
from tqdm.asyncio import tqdm_asyncio

from ark_nav.domains.shouxian.prompts import GENERATE_COT_PROMPT_V1, INTENTION_CLASSIFY_COT_PROMPT, INTENTION_CLASSIFY_TRAIN_COT_PROMPT
from ark_nav.domains.shouxian.services.shouxian_rag_service import ShouxianRAGService
from ark_nav.core.services.xiezhi_http import call_bigmodel_api
from ark_nav.core.utils.nav_logger import get_logger
from ark_nav.domains.shouxian.router_schemas import IntentResult, Message

logger = get_logger("ark_nav")

class IntentType(Enum):
    """意图类型枚举"""
    LIFE_INSURANCE = "寿险意图"  # 寿险相关意图
    REJECTED = "拒识"  # 无法识别的意图

class IntentCOTClassifier:

    def __init__(
        self,
        rag_models_handle,
        bert_model_handle,
        dedup_threshold: float = 0.75,
        top_k: int = 5,
        recall_k: int = 10,
        high_sim_threshold: float = 0.95,
        rules_path: Optional[str] = None,
    ):
        self.dedup_threshold = dedup_threshold
        self.top_k = top_k
        self.recall_k = recall_k
        self.high_sim_threshold = high_sim_threshold
        self.bert = bert_model_handle
        self.rag_service = ShouxianRAGService(rag_models_handle)

    def build_examples(self, examples: List[Tuple[Dict[str, Any], float]]) -> str:
        """构建Few-Shot提示词"""
        examples_text = []
        for i, (chain, sim) in enumerate(examples, 1):
            examples_text.append(
                f"示例{i} (相似度:{sim:.3f}):\n"
                f"问题: {chain['text']}\n"
                f"分析: {chain['cot_feedback']}\n"
                f"判断: {chain['label']}\n"
            )
        cot_examples = "\n".join(examples_text)
        return cot_examples

    async def generate_cot(self, question: str, intention:str = ""):
        """
        调用 OpenAI 接口判断用户意图是否属于寿险范畴。

        Args:
            user_message (str): 用户最新输入
        """
        if not all([question]):
            raise ValueError("缺少必要参数: user_message")

        scene_id = os.getenv("INTENT_REWRITE_SCENE_ID") or ""
        intent_rewrite_app_key = os.getenv("INTENT_REWRITE_APP_KEY") or ""
        intent_rewrite_app_secret = os.getenv("INTENT_REWRITE_APP_SECRET") or ""

        examples = self.rag_service.search(question)

        # if examples and examples[0][1] >= 0.9:
        #     best_chain, best_sim = examples[0]

        cot_examples = self.build_examples(examples)
        prompt = GENERATE_COT_PROMPT_V1.format(cot_examples=cot_examples,question=question,intention=intention)

        # logger.info(f"查询到思维链例子: {examples}")
        try:
            response = await call_bigmodel_api(
                query=prompt,
                scene_id=scene_id,
                app_key=intent_rewrite_app_key,
                app_secret=intent_rewrite_app_secret
            )

            result = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            # logger.info(f"模型返回:{result}")

            return question, result

        except Exception as e:
            logger.error(f"请求异常:{str(e)}")
            return question, """{
    "label": "error",
    "match_sample": False,
    "cot_feedback": "empty",
    "business_type": "empty"
}
"""

    async def classify_with_cot_rules(self, question: str, history):
        """
        调用 OpenAI 接口判断用户意图是否属于寿险范畴。

        Args:
            user_message (str): 用户最新输入
        """
        if not all([question]):
            raise ValueError("缺少必要参数: user_message")

        scene_id = os.getenv("INTENT_REWRITE_SCENE_ID") or ""
        intent_rewrite_app_key = os.getenv("INTENT_REWRITE_APP_KEY") or ""
        intent_rewrite_app_secret = os.getenv("INTENT_REWRITE_APP_SECRET") or ""
        examples = await self.rag_service.search(question)

        best_chain, best_score = examples[0]
        bert_result = None
        if best_score >= self.high_sim_threshold:
            example_label = "寿险意图" if best_chain["label"] == "寿险" else "拒识"
            bert_result = await self.bert.classify_user_intent.remote(question,return_details=True)
            if bert_result["result"] == example_label and bert_result["probs"] > 0.8:
                result = IntentResult(best_chain["label"],"llm_cot_rules_matched", extra={"bert_result": bert_result,"examples":examples})
                return result

        cot_examples = self.build_examples(examples)
        prompt = INTENTION_CLASSIFY_COT_PROMPT.format(cot_examples=cot_examples,question=question)

        # logger.info(f"查询到思维链例子: {examples}")
        try:
            response = await call_bigmodel_api(
                query=prompt,
                scene_id=scene_id,
                app_key=intent_rewrite_app_key,
                app_secret=intent_rewrite_app_secret
            )

            result_json = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            # logger.info(f"模型返回:{result}")
            result = "寿险意图" if json.loads(result_json).get("label") == "寿险" else "拒识"
            extra = {"raw_result": result_json, "examples": examples}
            if bert_result:
                extra["bert_result"] = bert_result
            intent_result = IntentResult(result,"llm_cot_rules_infer", extra=extra)
            return intent_result

        except Exception as e:
            logger.error(f"请求异常:{str(e)}")
            return IntentResult("error","llm_cot_rules", extra=str(e))

    async def classify_with_cot_model(self,
        user_message: str,
        history: Optional[List[Message]]) -> IntentResult:
        """
        调用 OpenAI 接口判断用户意图是否属于寿险范畴。

        Args:
            user_message (str): 用户最新输入
            history (str, optional): 自定义提示模板（可选）
        """
        app_key = os.getenv("EXP_APP_KEY")
        app_secret = os.getenv("EXP_APP_SECRET")
        scene_id = os.getenv("EXP_SCENE_ID")
        # xiezhi_prompt = os.getenv("XIEZHI_PROMPT")

        if not all([user_message]):
            raise ValueError("缺少必要参数: user_message")

        query = INTENTION_CLASSIFY_TRAIN_COT_PROMPT.format(question = user_message)
        logger.info(f"意图识别Query: {user_message}")
        try:
            response = await call_bigmodel_api(
                query=query,
                scene_id=scene_id,
                app_key=app_key,
                app_secret=app_secret
            )

            result_json = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            result = self.extract_result(result_json)
            intent_result = IntentResult(result=result,source="cot_model",extra=result_json)
            logger.info(f"模型返回:{result}")
            return intent_result

        except Exception as e:
            logger.error(f"请求异常:{str(e)}")
            return "拒识"

    def extract_result(self,json_str):
        try:
            data = json.loads(json_str)
            return "寿险意图" if data.get("l") == 1 else "拒识"
        except (json.JSONDecodeError, TypeError):
            return None


async def training_data_augmentation():
    # 初始化
    classifier = IntentCOTClassifier(
        dedup_threshold=0.75,
        top_k=3)

    chains = classifier.load_data("D_1229_cots_std.xlsx")
    chains_2 = classifier.load_data("1_菜单扩写_cot_std.xlsx")
    combined =  chains + chains_2
    # chains = classifier.deduplicate(chains)
    classifier.build_index(combined)
    # result = await classifier.classify("御享分红26的佣金多少", use_llm=False)

    # df_raw = pd.read_excel("D_1228_all.xlsx") # 假设列名: question, label, cot
    df_raw = pd.read_excel("D_1229_all_std-1231.xlsx")
    df_raw['field_text'] = df_raw['field_text'].astype(str)

    results = []

    try:
        semaphore = asyncio.Semaphore(11)

        async def limited_process(row):
            async with semaphore:  # 限制并发
                return await classifier.generate_cot(str(row["field_text"]), row["label_value"])

        tasks = [limited_process(row) for _, row in df_raw.iterrows()]
        for coro in tqdm_asyncio.as_completed(tasks, total=len(tasks)):
            try:
                question,result_json = await coro
                result_raw = json.loads(result_json)
                result = {
                    "field_text": question,
                    "label": result_raw["label"],
                    "match_sample": result_raw["match_sample"],
                    "cot_feedback": result_raw["cot_feedback"],
                    "business_type": result_raw["business_type"],
                }
                results.append(result)
            except:
                continue
    except Exception as e:
        logger.error(f"出错了！！{e}", exc_info=True)

    result_df = pd.DataFrame(results)

    # 将结果拼接到原数据后面
    final_df = df_raw.merge(result_df,on="field_text",how='left',suffixes=('','_result'))

    # 4. 保存
    final_df.to_csv("D_1229_all_std-1231-std.csv", index=False, encoding='utf-8-sig')
    logger.info(f"清洗完成! 结果已保存!")


async def online_bad_case():
    # 初始化
    classifier = IntentCOTClassifier(
        dedup_threshold=0.75,
        top_k=3)

    chains = classifier.load_data("D_all_Cleaned_20251223_merged_cot.xlsx")
    # chains = classifier.deduplicate(chains)
    classifier.build_index(chains)

    df_raw = pd.read_excel("badcase1226.xlsx")  # 假设列名: question, label, cot

    results = []

    try:
        semaphore = asyncio.Semaphore(7)

        async def limited_process(row):
            async with semaphore:  # 限制并发
                return await classifier.generate_cot(row["客户问题"], use_llm=False)

        tasks = [limited_process(row) for _, row in df_raw.iterrows()]
        for coro in tqdm_asyncio.as_completed(tasks, total=len(tasks)):
            try:
                question,result_json = await coro
                result_raw = json.loads(result_json)
                result = {
                    "客户问题": question,
                    "label": result_raw["label"],
                    "match_sample": result_raw["match_sample"],
                    "cot_feedback": result_raw["cot_feedback"],
                    "business_type": result_raw["business_type"],
                }
                results.append(result)
            except:
                continue
    except Exception as e:
        logger.error(f"出错了！！{e}", exc_info=True)

    result_df = pd.DataFrame(results)

    # 将结果拼接到原数据后面
    final_df = df_raw.merge(result_df,on="客户问题",how='left',suffixes=('','_result'))

    # 4. 保存
    final_df.to_csv("badcase1226_cot.csv", index=False, encoding='utf-8-sig')
    logger.info(f"清洗完成! 结果已保存!")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    # asyncio.run(online_bad_case())
    asyncio.run(training_data_augmentation())
