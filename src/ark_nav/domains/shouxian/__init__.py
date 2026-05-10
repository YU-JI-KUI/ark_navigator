
from ark_nav.domains.shouxian.agents.nav_agent import NavAgentDeployment
from ark_nav.domains.shouxian.models.bert import ShouxianBertDeployment
from ark_nav.domains.shouxian.agents.intent_classify_agent import (
    IntentClassifierDeployment,
    IntentClassifyAgentDeployment,  # DEPRECATED alias，兼容下次 release
)

__all__ = [
    "ShouxianBertDeployment",
    "NavAgentDeployment",
    "IntentClassifierDeployment",
    "IntentClassifyAgentDeployment",  # DEPRECATED alias
]
