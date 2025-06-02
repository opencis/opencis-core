import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from typing import List
from memory_backend import StructuredMemoryAdapter


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    if not np.any(vec1) or not np.any(vec2):
        return 0.0
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))


class MemoryVectorSearch(BaseRetriever):
    def __init__(self, store: StructuredMemoryAdapter, embedding_model: Embeddings):
        self.store = store
        self.embedding_model = embedding_model

    async def add_documents(self, documents: List[Document]) -> None:
        for i, doc in enumerate(documents):
            key = f"doc_{i}"
            await self.store.set(f"{key}_text", doc.page_content.encode())
            await self.store.set(f"{key}_meta", str(doc.metadata).encode())
            embedding = self.embedding_model.embed_query(doc.page_content)
            await self.store.set(f"{key}_vec", np.array(embedding).astype(np.float32).tobytes())
        await self.store.set("doc_count", str(len(documents)).encode())

    async def _get_relevant_documents(self, query: str) -> List[Document]:
        count_bytes = await self.store.get("doc_count")
        if not count_bytes:
            return []

        num_docs = int(count_bytes.decode())
        query_embedding = np.array(self.embedding_model.embed_query(query), dtype=np.float32)

        best_score = -1
        best_doc = None

        for i in range(num_docs):
            key = f"doc_{i}"
            vec_bytes = await self.store.get(f"{key}_vec")
            if not vec_bytes:
                continue

            stored_vec = np.frombuffer(vec_bytes, dtype=np.float32)
            score = cosine_similarity(query_embedding, stored_vec)
            if score > best_score:
                best_score = score
                best_doc = key

        if best_doc is None:
            return []

        text_bytes = await self.store.get(f"{best_doc}_text")
        meta_bytes = await self.store.get(f"{best_doc}_meta")
        text = text_bytes.decode() if text_bytes else ""
        metadata = eval(meta_bytes.decode()) if meta_bytes else {}
        return [Document(page_content=text, metadata=metadata)]
