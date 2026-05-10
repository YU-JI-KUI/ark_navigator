"""配置管理"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dev_mode: bool = False
    # 模型配置
    embedding_model: str = "/ark-nav/models/xiaobu-embedding-v2"
    rerank_model: str = "/ark-nav/models/bge-reranker-base"
    bert_model: str = "/ark-nav/models/bert_shouxian_base"

    # 批处理配置（提高吞吐量）
    embedding_batch_size: int = 32
    batch_wait_timeout_ms: int = 3

    # 设备配置
    use_gpu: bool = False
    faiss_index_path: str = "./data/faiss_index"
    faiss_dimension: int = 768  # bge-base-zh
    top_k: int = 10
    rerank_threshold: float = 0.9

    # 服务配置
    port: int = 8080
    log_level: str = "INFO"  # DEBUG / INFO / WARNING / ERROR
    log_format: str = "text"  # json / text

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
