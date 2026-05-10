"""
意图识别服务
实现并行优化的意图识别策略：
1. 并行执行直接识别和重写后识别
2. 如果直接识别返回寿险意图则快速返回
3. 如果直接识别返回拒识和识别等待重写后的识别结果
"""

import asyncio
import json
import os
from typing import List, Optional
from ark_nav.domains.shouxian.intents import IntentType  # noqa: F401  保留 re-export 以兼容旧 import 路径

from ark_nav.domains.shouxian.intent_classifier_simple import classify_user_intent
from ark_nav.core.services.xiezhi_http import call_llm
from ark_nav.core.utils.nav_logger import get_logger
from ark_nav.domains.shouxian.router_schemas import IntentResult, Message

logger = get_logger("ark_nav")


class IntentClassifier:
    """
    实现并行优化策略的意图识别：
    1. 并行执行直接识别和重写后识别两个任务
    2. 如果直接识别返回寿险意图，立即返回结果
    3. 如果直接识别返回拒识，等待重写后识别的结果
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        timeout: float = 60.0
    ):
        """
        初始化意图识别器

        Args:
            intent_api_client: 意图识别API客户端（假定已实现）
            rewrite_api_client: 意图重写API客户端（假定已实现）
            timeout: 超时时间（秒）
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.timeout = timeout

    async def classify_user_intent_advance(
        self,
        current_query: str,
        history: Optional[List[Message]] = None
    ) -> IntentResult:
        """
        识别用户意图

        并行执行两个任务：
        1. 直接识别：直接用当前问题调用意图识别API
        2. 重写后识别：先重写意图，再调用识别API

        策略：
        - 如果直接识别返回"寿险意图"，立即返回
        - 如果直接识别返回"拒识"，等待重写后识别的结果

        Args:
            current_query: 当前用户问题
            history: 历史对话消息列表

        Returns:
            IntentResult: 意图识别结果
        """
        if history is None:
            history = []

        try:
            logger.info("创建两个并行任务")
            direct_task = asyncio.create_task(
                self._classify_direct(current_query)
            )

            rewrite_task = asyncio.create_task(
                self._recognize_with_rewrite(current_query, history)
            )

            logger.info("等待直接识别完成")
            done, pending = await asyncio.wait(
                fs=[direct_task, rewrite_task],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=self.timeout
            )

            if not done:
                direct_task.cancel()
                rewrite_task.cancel()
                raise TimeoutError(f"任务超时")

            direct_result = done.pop().result()

            # 如果直接识别返回寿险意图，立即返回
            if direct_result.result == "寿险意图":
                logger.info("返回寿险意图,无需重写，返回结果")
                if not rewrite_task.done():
                    rewrite_task.cancel()
                return direct_result

            # 如果直接识别返回拒识，等待重写后识别的结果
            if direct_result.result == "拒识":
                logger.info("返回拒识,结合历史，进行意图识别，进行再次确认")
                rewrite_result = await rewrite_task
                return rewrite_result

            # 其他情况，直接返回直接识别的结果
            if not rewrite_task.done():
                rewrite_task.cancel()
            return direct_result

        except asyncio.TimeoutError:
            raise TimeoutError(f"意图识别超时（{self.timeout}秒）")
        except Exception as e:
            raise RuntimeError(f"意图识别失败: {str(e)}")

    async def _classify_direct(self, query: str) -> IntentResult:
        """
        直接识别：使用当前问题直接调用意图识别API

        Args:
            query: 用户问题

        Returns:
            IntentResult: 识别结果
        """
        try:
            result = await classify_user_intent(self.app_key, self.app_secret, query)

            return IntentResult(
                result=result,
                source="direct"
            )
        except Exception as e:
            logger.info(f"意图识别失败:{e}")
            return IntentResult(
                result="error",
                source="direct"
            )

    async def _recognize_with_rewrite(
        self,
        query: str,
        history: List[Message]
    ) -> IntentResult:
        """
        重写后识别：先重写意图，再调用意图识别API

        Args:
            query: 用户问题
            history: 历史对话

        Returns:
            IntentResult: 识别结果
        """
        try:
            scene_id = os.getenv("INTENT_REWRITE_SCENE_ID")
            intent_rewrite_app_key = os.getenv("INTENT_REWRITE_APP_KEY")
            intent_rewrite_app_secret = os.getenv("INTENT_REWRITE_APP_SECRET")
            baize_prompt = os.getenv("BAIZE_PROMPT")
            prompt = baize_prompt or """# 角色
你是一个"保守型"用户意图优化器。你的目标是仅在必要时修复用户输入的语义完整性，保持"最小修改"原则。

# 优化规则（必须按顺序判断）

1. **判断完整性**：
   - 检查**[用户输入]**是否意图清晰、指代明确？
   - **典型场景**：
     - 指令类："转人工"、"退出"、"结束"、"联系客服"、"查询保单"。
     - 完整句："我想查询车险的价格"、"如何理赔"。
     - 全新话题/语义断裂：用户输入了和上文（历史对话）**完全无关**的内容，例如从保险跳转到"做饭"、"天气"、"减肥"。**严禁**逐行建立联系
   - **动作**：如果是上述情况，**不做任何修改**，直接输出原话。

2. **判断纯名词**：
   - 如果用户输入仅仅是一个**独立的、且非上下文属性的**名词/实体（例如："糖尿病"、"犹豫期"、"现金价值"）。
   - **动作**：将其改写为定义型问句："什么是[名词]？"。

3. **指代与属性补全 (Contextual Refinement)**：
   - 仅当输入包含**指代词**（"它"、"那个"、"这个"）或**明显缺失主语/修饰语**（例如上下文在聊某款保险，用户只问"价格"、"保额"）时。
   - **动作**：结合[历史对话]补全缺失的实体。

# 输出格式-JSON
{{
    "rewrite_type": "original / expansion / completion",  // 标记你的操作类型
    "rewritten_query": "最终的重写结果字符串"  # 重写后的意图**rewritten_query**不得超过 30 个汉字。
}}

## 示例 1：意图清晰/指令（直接透传）
历史对话：[User: 我想换人, AI: 请选择操作]
用户输入："转人工"
Output:
{{
    "rewrite_type": "original",
    "rewritten_query": "转人工"
}}

## 示例 2：纯名词（改写为定义问句）
历史对话：[User: 买了重疾险, AI: 好的]
用户输入："犹豫期"
Output:
{{
    "rewrite_type": "expansion",
    "rewritten_query": "什么是犹豫期？"
}}

## 示例 3：上下文属性缺失（补全）
历史对话：[User: 泰康人寿的这款产品怎么样？, AI: 性价比很高。]
用户输入："价格呢？"
Output:
{{
    "rewrite_type": "completion",
    "rewritten_query": "泰康人寿这款产品的价格是多少？"
}}

## 示例 4：指代词（补全）
历史对话：[User: 推荐一款意外险，AI: 这款百万身价不错。]
用户输入："它包含猝死吗？"
Output:
{{
    "rewrite_type": "completion",
    "rewritten_query": "这款百万身价意外险包含猝死责任吗？"
}}

## 示例 5：话题跳跃（补全）
历史对话：[User: 推荐一款意外险，AI: 这款百万身价不错。]
用户输入："如何减肥"
Output:
{{
    "rewrite_type": "original",
    "rewritten_query": "如何减肥"
}}

**输入数据：**
[历史对话]：
{history}
[用户输入]：
{query}

**开始：****"""
            full_query = prompt.format(history=history, query=query)
            logger.info(f"用户输入-{query},历史-{history}")

            response = await call_llm(
                query=full_query,
                scene_id=scene_id,
                app_key=intent_rewrite_app_key,
                app_secret=intent_rewrite_app_secret
            )

            rewritten_query = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            logger.info(f"rewritten query is: {rewritten_query}")
            try:
                parsed = json.loads(rewritten_query)
                if isinstance(parsed, dict) and "rewritten_query" in parsed:
                    rewritten_query = parsed["rewritten_query"].strip()
                elif isinstance(parsed, str):
                    rewritten_query = parsed.strip()
            except json.JSONDecodeError:
                logger.warning(
                    f"rewrite query is not str or json string with \"rewritten_query\" field: {rewritten_query}",
                    rewritten_query)

            # 步骤2：使用重写后的问题调用意图识别API
            result = await self._classify_direct(rewritten_query)
            result.source = "rewrite"
            return result

        except Exception as e:
            # 如果重写后识别失败，返回拒识结果
            logger.info(f"rewritten query failed:{e}")
            return IntentResult(
                result="error",
                source="rewrite"
            )


if __name__ == "__main__":
    # 运行示例
    from dotenv import load_dotenv

    load_dotenv()
    classifier = IntentClassifier(app_key="Ym5NPfPrgp8sZ8LkcpR5pqQwsLEoo4z0",
                                  app_secret="OYqUvt8RNtvW7DqPDqM8SfWdtcroQCq5")
    result = asyncio.run(classifier.classify_user_intent_advance("安有护"))
    logger.info(result)
