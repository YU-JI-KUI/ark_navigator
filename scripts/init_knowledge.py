"""初始化知识库"""

import json
from typing import Any, Dict, List
import faiss
import numpy as np
from pathlib import Path
import pandas as pd
from sentence_transformers import SentenceTransformer

from ark_nav.core.utils.nav_logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def build_index(embedding_model,chains: List[Dict[str, Any]]):
    """构建双索引"""
    texts = [c.get("text", "") for c in chains]

    logger.info("构建Dense索引...")
    embeddings = embedding_model.encode(
        texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True
    )
    dense_index = faiss.IndexFlatIP(embeddings.shape[1])
    dense_index.add(embeddings.astype('float32'))
    logger.info(f"索引构建完成: {len(chains)}条")
    return dense_index


def load_data(path: str) -> List[Dict[str, Any]]:
    """加载数据"""
    logger.info(f"加载数据: {path}")
    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    ext = file_path.suffix.lower()

    if ext == '.xlsx':
        df = pd.read_excel(path, engine='openpyxl')
        df.columns = df.columns.str.strip()

        cols_map = {col.lower(): col for col in df.columns}
        required = ["text", "label", "cot_feedback"]
        missing = [c for c in required if c not in cols_map]
        if missing:
            raise ValueError(f"缺少列: {missing}")

        df = df[[cols_map[c] for c in required]]
        df.columns = required
        chains = df.to_dict('records')

        for chain in chains:
            for k in chain:
                chain[k] = "" if pd.isna(chain[k]) else str(chain[k]).strip()

    elif ext == '.json':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        chains = data if isinstance(data, list) else data.get("data", [])

    else:
        raise ValueError(f"不支持的格式: {ext}")

    chains = [c for c in chains if c.get("text", "").strip() and c.get("cot_feedback", "").strip()]
    logger.info(f"加载完成: {len(chains)}条")
    return chains


def init_cot_rules(embedding_model):
    chains = load_data("data/D_1229_cots_std.xlsx")
    chains_2 = load_data("data/1_菜单扩写_cot_std.xlsx")
    combined =  chains + chains_2
    return build_index(embedding_model,combined)


def main():
    """初始化知识库和FAISS索引"""

    logger.info("初始化知识库...")

    # 创建数据目录
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)

    # 创建FAISS索引
    logger.info("创建FAISS索引...")

    model = SentenceTransformer("./models/bge-base-zh-v1.5")

    index = init_cot_rules(model)

    # 保存索引
    index_path = data_dir / "faiss_index"
    faiss.write_index(index, str(index_path))

    logger.info(f"FAISS索引已保存: {index_path}")
    logger.info(f"向量维度: 向量数量: {index.ntotal}")
    logger.info("\n初始化完成! ")


if __name__ == "__main__":
    main()
