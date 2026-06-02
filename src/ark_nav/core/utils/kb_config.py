"""知识库（KnowledgeBase）配置。
"""
import os


class KBConfig:
    """知识库配置（模式 + 同步策略）"""

    # 实现模式："local"（本地 FAISS）/ "remote"（远程 REST API）
    # 全局默认 remote（保守）；生产环境应通过 .env 显式设置 KB_MODE=local
    # 每个 deployment 还可通过专属 env（如 SHOUXIAN_KB_MODE / YLX_KB_MODE）覆盖全局
    MODE = os.getenv("KB_MODE", "remote")

    # 全量同步时间（HH:MM, 24 小时制）：每天一次刷新所有 FAQ + Table
    FULL_SYNC_TIME = os.getenv("KB_FULL_SYNC_TIME", "21:30")

    # 增量同步间隔（分钟）
    PARTIAL_SYNC_INTERVAL_MINUTES = int(os.getenv("KB_PARTIAL_SYNC_INTERVAL_MINUTES", "30"))

    # 增量同步的目录 ID（单值）：每 N 分钟只拉这个 categoryId 下的 FAQ，
    # 替换本地相应目录的 FAQ；其他目录的 FAQ 和所有 Table 保持不变
    PARTIAL_FAQ_CATEGORY_ID = os.getenv("KB_PARTIAL_FAQ_CATEGORY_ID", "") or ""

    @classmethod
    def is_local_mode(cls) -> bool:
        return cls.MODE.lower() == "local"

    @classmethod
    def is_remote_mode(cls) -> bool:
        return cls.MODE.lower() == "remote"

    @classmethod
    def partial_category_id(cls) -> str:
        """返回增量目录 ID（去空白）。空字符串表示未配置。"""
        return cls.PARTIAL_FAQ_CATEGORY_ID.strip()

    @classmethod
    def check_required(cls):
        """启动期校验。MODE 值合法即可，其他都有默认值。"""
        if cls.MODE.lower() not in ("local", "remote"):
            raise ValueError(f"KB_MODE 取值必须为 'local' 或 'remote'，当前为: {cls.MODE!r}")
