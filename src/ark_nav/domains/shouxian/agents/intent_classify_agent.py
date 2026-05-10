""" 多级Agent：检索 → BERT判断 → 知识库/BOB"""
import os
from fastapi import HTTPException
from ray import serve
from ark_nav.core.utils.nav_logger import get_logger, setup_logging, print_execution_time
from ark_nav.domains.shouxian.intent_classifier_advanced import IntentClassifier
from ark_nav.domains.shouxian.intent_classifier_cot import IntentCOTClassifier
from ark_nav.domains.shouxian.intent_classifier_simple import classify_user_intent
from ark_nav.domains.shouxian.router_schemas import COTType, IntentRequest, IntentResult
from ark_nav.core.utils.httpx_deployment_decorator import with_http_client

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 10))
INITIAL_REPLICAS = int(os.getenv("RAY_INITIAL_REPLICAS", 10))


@serve.deployment(
    # 显式锁定 deployment name 为旧类名，避免改 Python 类名时影响 Ray Dashboard
    # 上的 actor 名 / Prometheus metrics label / 运维 grep 规则。
    # 可在下次大版本同步部署侧后再移除（命名规范整改 2026-05）
    name="IntentClassifyAgentDeployment",
    max_ongoing_requests=20,
    ray_actor_options={
        "num_cpus": 0.5,
    },
    autoscaling_config={
        "min_replicas": MIN_REPLICAS,
        "max_replicas": 16,
        "initial_replicas": INITIAL_REPLICAS,
        "target_ongoing_requests": 5,
        "upscale_delay_s": 3,
        "downscale_delay_s": 60,
        "upscaling_factor": 1.0,
    }
)
@with_http_client()
class IntentClassifierDeployment:
    """寿险意图分类 Ray Serve Deployment（多级编排：RAG → BERT → LLM）。

    2026-05 命名规范整改：原类名 IntentClassifyAgentDeployment 双后缀冗余
    （Agent + Deployment），重命名为 IntentClassifierDeployment，
    旧名作为 alias 保留至下次 release。

    部署 name 仍是 "IntentClassifyAgentDeployment"（Ray Dashboard / metrics
    标识符），与运维约定保持兼容。
    """

    def __init__(self, rag_models_handle, bert_handle):
        setup_logging()
        self.rag_models_handle = rag_models_handle
        self.bert = bert_handle

        self.intent_cot_classifier = IntentCOTClassifier(rag_models_handle, bert_handle)
        self.logger = get_logger("ark_nav")
        self.logger.info("[IntentClassifyAgent] 初始化完成")

    @print_execution_time
    async def classify_intent(self, request: IntentRequest) -> IntentResult:
        """
        接收 app_key、app_secret 和 user_message，返回意图分类结果。
        打印请求头和请求体日志。
        """
        try:
            if (not request.cot_type) or (request.cot_type == COTType.NO_COT):
                self.logger.debug("classify without COT")
                return await self._internal_classify_without_cot(request)

            if request.cot_type and request.cot_type == COTType.COT_MODEL:
                self.logger.debug("classify with COT model")
                return await self._internal_classify_with_cot_model(request)

            if request.cot_type and request.cot_type == COTType.LLM_WITH_COT_RULES:
                self.logger.debug("classify with COT rules")
                return await self._internal_classify_with_llm_rules(request)

            return IntentResult("No Result", "No Source")

        except Exception as e:
            self.logger.error(f"分类失败: {str(e)}", exc_info=True)  # 打印完整堆栈
            raise HTTPException(status_code=500, detail=f"分类失败: {str(e)}")

    async def _internal_classify_with_cot_model(self, request: IntentRequest) -> IntentResult:
        """
        占位方法：处理 COT_MODEL 类型的请求。
        """
        return await self.intent_cot_classifier.classify_with_cot_model(request.user_message, request.history)

    async def _internal_classify_with_llm_rules(self, request: IntentRequest) -> IntentResult:
        """
        占位方法：处理 LLM_WITH_COT_RULES 类型的请求。
        """
        return await self.intent_cot_classifier.classify_with_cot_rules(request.user_message, request.history)

    async def _internal_classify_without_cot(self, request) -> IntentResult:
        """
        统一处理意图识别逻辑，支持拒绝确认场景与直接分类场景。

        Args:
            request: 请求对象，包含 app_key, app_secret, user_message, history, reject_reconfirm 等字段。

        Returns:
            IntentResult: 意图分类结果。
        """
        if request.reject_reconfirm:
            self.logger.debug("reject_reconfirm is True, call classify_user_intent_advance")
            intent_recongnizer = IntentClassifier(request.app_key, request.app_secret)
            result = await intent_recongnizer.classify_user_intent_advance(
                current_query=request.user_message,
                history=request.history
            )
            return result
        else:
            self.logger.debug("reject_reconfirm is False, call classify_user_intent")
            result = await classify_user_intent(
                app_key=request.app_key,
                app_secret=request.app_secret,
                user_message=request.user_message
            )
            return IntentResult(
                result=result,
                source="direct"
            )


# DEPRECATED: 用 IntentClassifierDeployment 代替，保留至下次 release 后删除（命名规范整改 2026-05）
IntentClassifyAgentDeployment = IntentClassifierDeployment
