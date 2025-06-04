"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from typing import List, Optional, Any
import numpy as np

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables.config import RunnableConfig

from opencis.apps.backend.memory_backend import StructuredMemoryAdapter


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    denom = norm1 * norm2
    return float(np.dot(vec1, vec2) / denom) if denom else 0.0


def l2_distance(vec1: np.ndarray, vec2: np.ndarray) -> float:
    return float(np.sum((vec1 - vec2) ** 2))


def inner_product_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    return float(np.dot(vec1, vec2))


class MemoryVectorSearch(BaseRetriever):
    def __init__(self, store: StructuredMemoryAdapter, embedding_model: Embeddings, **kwargs: Any):
        super().__init__(**kwargs)
        object.__setattr__(self, "_store", store)
        object.__setattr__(self, "_embedding_model", embedding_model)
        # List[Tuple[vec_addr, vec_size, doc_addr, doc_size]]
        object.__setattr__(self, "_index", [])
        self._similarity_fn = cosine_similarity

    async def add_documents(self, documents: List[Document]) -> None:
        texts = [doc.page_content for doc in documents]
        embeddings = self._embedding_model.embed_documents(texts)

        for embedding, document in zip(embeddings, documents):
            vec_bytes = np.array(embedding, dtype=np.float32).tobytes()
            vec_addr, vec_size = await self._store.store_object(vec_bytes)

            doc_bytes = document.model_dump_json().encode("utf-8")
            doc_addr, doc_size = await self._store.store_object(doc_bytes)

            self._index.append((vec_addr, vec_size, doc_addr, doc_size))

    def _get_relevant_documents(self, query: str, **kwargs: Any) -> List[Document]:
        raise NotImplementedError("Sync method not supported. Use `ainvoke()` or `arun()`.")

    def get_relevant_documents(
        self,
        query: str,
        *,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> List[Document]:
        raise NotImplementedError("This retriever is async-only. Use ainvoke().")

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> List[Document]:
        # pylint: disable=unused-argument
        return await self._async_get_relevant_documents(query, 4)

    async def _async_get_relevant_documents(self, query: str, k: int) -> List[Document]:
        scores = []
        query_vec = np.array(self._embedding_model.embed_query(query), dtype=np.float32)
        for vec_addr, vec_size, doc_addr, doc_size in self._index:
            vec_bytes = await self._store.load_object(vec_addr, vec_size)
            vec = np.frombuffer(vec_bytes, dtype=np.float32)
            similarity = self._similarity_fn(query_vec, vec)
            scores.append((similarity, doc_addr, doc_size))

        scores.sort(key=lambda x: -x[0])
        top_k = scores[:k]

        results = []
        for _, doc_addr, doc_size in top_k:
            doc_bytes = await self._store.load_object(doc_addr, doc_size)
            doc_str = doc_bytes.decode("utf-8")
            results.append(Document.model_validate_json(doc_str))

        return results
