"""配置管理"""
from enum import Enum

from pydantic_settings import BaseSettings


class KnowledgeBaseMode(str, Enum):
    """知识库实现模式"""
    LOCAL = "local"     # 本地 FAISS 索引
    REMOTE = "remote"   # 远程智能体平台 REST API


class Settings(BaseSettings):
    dev_mode: bool = False
    # 模型配置
    embedding_model: str = "/ark-nav/models/xiaobu-embedding-v2"

    # 批处理配置（提高吞吐量）
    embedding_batch_size: int = 32
    batch_wait_timeout_ms: int = 3

    # 设备配置
    use_gpu: bool = False
    faiss_index_path: str = "./data/faiss_index"
    faiss_dimension: int = 768  # bge-base-zh
    top_k: int = 10

    # 知识库配置
    kb_mode: KnowledgeBaseMode = KnowledgeBaseMode.LOCAL

    # === 知识库同步策略 ===
    # 全量同步：每天一次，刷新所有 FAQ + Table
    kb_full_sync_time: str = "21:30"  # HH:MM 24 小时制
    # 增量同步：高频刷新指定 label 的 FAQ（不影响 table）
    kb_partial_sync_interval_minutes: int = 30
    kb_partial_faq_labels: str = "hotfix"  # 多个标签用英文逗号分隔，如 "hotfix,urgent"

    # 兼容旧配置：如果运维只设了 KB_SYNC_TIME 而没设 KB_FULL_SYNC_TIME，
    # 代码侧会回退使用此字段（详见 kb_full_sync_time_effective property）
    kb_sync_time: str = ""  # 已 deprecated，请使用 kb_full_sync_time

    @property
    def kb_full_sync_time_effective(self) -> str:
        """读取生效的全量同步时间，优先 kb_full_sync_time，回退到老的 kb_sync_time"""
        return self.kb_full_sync_time or self.kb_sync_time or "21:30"

    @property
    def kb_partial_faq_labels_list(self) -> list[str]:
        """把逗号分隔的标签字符串解析为列表"""
        raw = self.kb_partial_faq_labels or ""
        return [s.strip() for s in raw.split(",") if s.strip()]

    # 服务配置
    port: int = 8080
    log_level: str = "INFO"  # DEBUG / INFO / WARNING / ERROR
    log_format: str = "text"  # json / text

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
