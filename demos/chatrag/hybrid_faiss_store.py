
import faiss
import numpy as np
from typing import List, Optional, Callable, Awaitable
from langchain_core.vectorstores import VectorStore
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from memory_backend import StructuredMemoryAdapter

from langchain_core.retrievers import BaseRetriever
from pydantic import Field

class HybridRetriever(BaseRetriever):
    similarity_search_fn: Callable[[str], Awaitable[List[Document]]] = Field(exclude=True)

    async def aget_relevant_documents(self, query: str):
        return await self.similarity_search_fn(query)

    def _get_relevant_documents(self, query: str):
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            task = asyncio.create_task(self.similarity_search_fn(query))
            return loop.run_until_complete(asyncio.shield(task))
        else:
            return loop.run_until_complete(self.similarity_search_fn(query))



class HybridFAISSStore(VectorStore):
    def __init__(
        self,
        embeddings: Embeddings,
        backend: StructuredMemoryAdapter,
        use_memory_backend: bool = True,
    ):
        self._embeddings = embeddings
        self.backend = backend
        self.use_memory_backend = use_memory_backend

        self.index = None
        self.documents: List[Document] = []

    async def initialize(self):
        if self.use_memory_backend:
            try:
                restored = await self.backend.load_object(self.index_addr, self.index_size)
                self.index = restored.get("index")
                self.documents = restored.get("documents", [])
            except Exception:
                pass

        if self.index is None:
            dim = len(self._embeddings.embed_query("test"))
            self.index = faiss.IndexFlatL2(dim)

    async def add_documents(self, documents: List[Document]) -> None:
        texts = [doc.page_content for doc in documents]
        embeddings = np.array(self._embeddings.embed_documents(texts)).astype("float32")
        self.index.add(embeddings)
        self.documents.extend(documents)

        if self.use_memory_backend:
            addr, size = await self.backend.store_object({
                "index": self.index,
                "documents": self.documents
            })
            self.index_addr = addr
            self.index_size = size

    async def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        embedding = np.array([self._embeddings.embed_query(query)]).astype("float32")
        D, I = self.index.search(embedding, k)
        return [self.documents[i] for i in I[0] if i < len(self.documents)]

    @classmethod
    async def from_texts(
        cls,
        texts: List[str],
        embedding: Embeddings,
        backend: StructuredMemoryAdapter,
        use_memory_backend: bool = True,
        metadatas: Optional[List[dict]] = None,
    ) -> "HybridFAISSStore":
        docs = [Document(page_content=text, metadata=metadatas[i] if metadatas else {}) for i, text in enumerate(texts)]
        store = cls(embeddings=embedding, backend=backend, use_memory_backend=use_memory_backend)
        await store.initialize()
        await store.add_documents(docs)
        return store

    async def as_retriever(self):return HybridRetriever(similarity_search_fn=self.similarity_search)
