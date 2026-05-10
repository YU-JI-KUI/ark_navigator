"""BERT-base 一致性判断应用"""
import os
from ray import serve
import torch.nn.functional as F
from typing import List, Optional, Dict, Any
import torch
from ark_nav.config import settings
from ark_nav.core.utils.nav_logger import get_logger,print_execution_time

MIN_REPLICAS = int(os.getenv("RAY_MIN_REPLICAS", 1))

LABEL_DICT = {
    '拒识': 0,
    '寿险意图': 1,
}
LABEL_LIST = [k for k, _ in sorted(LABEL_DICT.items(), key=lambda x: x[1])]

@serve.deployment(
    name="xiezhi-bert",
    ray_actor_options={"num_gpus": 0.2 if settings.use_gpu else 0},
    autoscaling_config={
        "min_replicas": MIN_REPLICAS,
        "max_replicas": 4,
        "target_num_ongoing_requests_per_replica": 20
    }
)
class ShouxianBertDeployment:
    """BERT-base一致性判断模型"""
    temperature = 2
    energy_threshold_high = -1 #
    energy_threshold_low = -3.7875831127166675  # 85%的置信区间

    def __init__(self):
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        self.logger = get_logger("ark_nav")
        self.device = "cuda" if torch.cuda.is_available() and settings.use_gpu else "cpu"
        print(f"[BERT] 加载模型到 {self.device}")
        self.is_model_loaded = False
        self.tokenizer = AutoTokenizer.from_pretrained(settings.bert_model)
        self.model = AutoModelForSequenceClassification.from_pretrained(settings.bert_model, num_labels=len(LABEL_LIST))
        self.model.to(self.device)
        self.model.eval()

        test_input = self.tokenizer("测试输入", return_tensors="pt")
        inputs_on_device = {key: tensor.to(self.device) for key, tensor in test_input.items()}
        with torch.no_grad():
            output = self.model(**inputs_on_device)
        self.logger.info(f"模型加载测试结果: {output}")
        self.is_model_loaded = True

        print(f"[BERT] 模型加载完成")

    def compute_energy(self,logits: torch.Tensor, temperature: float = 1.0) -> torch.Tensor:
        """
        计算Energy分数

        公式: Energy = -T * log(sum(exp(logits/T)))
             = -T * logsumexp(logits/T)

        Args:
            logits: [batch_size, num_classes] 模型输出的logits
            temperature: 温度参数
        Returns:
            energy: [batch_size] 每个样本的energy值
        """
        energy = -temperature * torch.logsumexp(logits / temperature, dim=-1)
        return energy

    def update_thresholds(self,threshold_low: float, threshold_high: float):
        """
        更新Energy阈值（用于动态调整）

        Args:
            threshold_low: 新的低阈值
            threshold_high: 新的高阈值
        """
        energy_threshold_low = threshold_low
        energy_threshold_high = threshold_high
        print(f"阈值已更新: low={threshold_low:.3f}, high={threshold_high:.3f}")
        return "success"

    def classify_intent_based_energy(self,logits, pred_label_idx) -> Dict:
        energy = self.compute_energy(logits, self.temperature).item()
        self.logger.error(f"energy:{energy}, energy_threshold_low:{energy_threshold_low:.3f} ,energy_threshold_high:{energy_threshold_high:.3f}")
        if energy > energy_threshold_high:
            final_label = "拒识"
            confidence = "low"
            decision_reason = f"Energy:{energy:.3f} > {energy_threshold_high:.3f}, 判定为OOD,BERT快路径拒识类"
        elif energy < energy_threshold_low:
            final_label = LABEL_LIST[pred_label_idx]
            confidence = "high"
            decision_reason = f"Energy:{energy:.3f} < {energy_threshold_low:.3f}, BERT快路径返回"
        else:
            final_label = "不确定"
            confidence = "medium"
            decision_reason = f"Energy:{energy:.3f} 在阈值区间，不确定（建议LLM验证）"

        details = {
            "energy": energy,
            "logits": str(logits),
            "result": final_label,
            "confidence":confidence,
            "reason": decision_reason,
        }

        return details

    @print_execution_time
    def classify_user_intent(self,user_message:str, energe_base = False, return_details:bool = False) -> Dict:
        if not self.is_model_loaded:
            raise SystemError("模型未加载")

        inputs = self.tokenizer(
            f"#来源: 寿险app #问题:{user_message}",
            add_special_tokens=False,
            return_tensors="pt",
            truncation=True,
            padding=False,
            max_length=512
        )
        # 推理
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze(0)
            probs = F.softmax(logits, dim=-1)
            prod_reject = probs[0].item()
            prob_shouxian = probs[1].item()
            # prob_other = probs[2].item() revert to 2 categories
            pred_label_idx = int(torch.argmax(probs).item())

        self.logger.info(f"logits:{logits}")
        self.logger.info(f"BERT:寿险意图概率:{prob_shouxian*100:.2f}%, 拒识概率:{prod_reject*100:.2f}%")

        details = {
            "logits": str(logits),
            "probs": probs[pred_label_idx].item(),
            "result": LABEL_LIST[pred_label_idx],
        }
        if energe_base:
            details = classify_intent_based_energy(logits, pred_label_idx)
            details["probs"] = str(probs)

        if return_details:
            return details
        else:
            return {"result": details["result"]}


if __name__ == "__main__":
    import ray
    import asyncio

    ray.init()
    serve.run(ShouxianBertDeployment.bind())

    async def test():
        handle = serve.get_deployment_handle("xiezhi-bert", "default")
        score = await handle.classify_user_intent.remote("你好")
        print(f"一致性分数: {score}")

    asyncio.run(test())
