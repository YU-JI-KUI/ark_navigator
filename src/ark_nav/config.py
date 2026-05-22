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
    kb_sync_time: str = "21:30"  # 每日同步时间，HH:MM 24 小时制

    # 服务配置
    port: int = 8080
    log_level: str = "INFO"  # DEBUG / INFO / WARNING / ERROR
    log_format: str = "text"  # json / text

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
