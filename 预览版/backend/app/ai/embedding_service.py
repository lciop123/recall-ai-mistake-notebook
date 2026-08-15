# -*- coding: utf-8 -*-
"""embedding + ChromaDB 服务（可选依赖）。

未安装 sentence-transformers 时全部 no-op（语义搜索降级为 LIKE 关键词搜索）。
"""
import logging
from typing import Optional

from app.core.config import CHROMA_DIR, BGE_MODEL_NAME

logger = logging.getLogger(__name__)
_model = None
_client = None
_collection = None
_LOAD_FAILED = False

COLLECTION_NAME = "questions_embedding"


def available() -> bool:
    return _model is not None


def _get_model():
    global _model, _LOAD_FAILED
    if _model is not None:
        return _model
    if _LOAD_FAILED:
        return None
    try:
        from sentence_transformers import SentenceTransformer  # 可选依赖
        _model = SentenceTransformer(BGE_MODEL_NAME)
        logger.info("Embedding 模型加载完成: %s", BGE_MODEL_NAME)
        return _model
    except Exception as e:
        _LOAD_FAILED = True
        logger.warning("Embedding 模型加载失败（降级为关键词搜索）: %s", e)
        return None


def _get_collection():
    global _client, _collection
    try:
        import chromadb
        if _client is None:
            _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        if _collection is None:
            _collection = _client.get_or_create_collection(COLLECTION_NAME)
        return _collection
    except Exception as e:
        logger.warning("ChromaDB 不可用（降级）: %s", e)
        return None


def embed(texts: list) -> Optional[list]:
    model = _get_model()
    if model is None:
        return None
    try:
        return model.encode(texts, normalize_embeddings=True).tolist()
    except Exception as e:
        logger.warning("embedding 失败: %s", e)
        return None


def upsert_question(qid: int, text: str):
    col = _get_collection()
    if col is None:
        return
    vec = embed([text])
    if vec is None:
        return
    col.upsert(ids=[str(qid)], embeddings=vec, metadatas=[{"id": qid}])


def delete_question(qid: int):
    col = _get_collection()
    if col is None:
        return
    try:
        col.delete(ids=[str(qid)])
    except Exception:
        pass


def search(text: str, top_k: int = 20) -> Optional[list]:
    """返回 [question_id, ...]，不可用时返回 None（调用方降级 LIKE）"""
    col = _get_collection()
    if col is None:
        return None
    vec = embed([text])
    if vec is None:
        return None
    try:
        res = col.query(query_embeddings=vec, n_results=top_k)
        ids = res.get("ids", [[]])[0]
        return [int(i) for i in ids if i.isdigit()]
    except Exception as e:
        logger.warning("向量检索失败: %s", e)
        return None
