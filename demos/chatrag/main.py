from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from langchain.chains import RetrievalQA
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama.llms import OllamaLLM
from langchain.text_splitter import RecursiveCharacterTextSplitter

from hybrid_faiss_store import HybridFAISSStore
from memory_backend import MemoryBackend, AlignedMemoryBackend, StructuredMemoryAdapter

import shutil
from pathlib import Path

UPLOAD_DIR = Path("uploads")
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize LLM and storage backend once
llm = OllamaLLM(model="gemma3:4b")
mem_backend = MemoryBackend()
aligned = AlignedMemoryBackend(mem_backend.load, mem_backend.store)
store = StructuredMemoryAdapter(aligned)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("chatui/index.html", {"request": request})

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    UPLOAD_DIR.mkdir(exist_ok=True)
    file_path = UPLOAD_DIR / file.filename

    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    ext = file_path.suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(str(file_path))
    else:
        loader = TextLoader(str(file_path), encoding="utf-8", autodetect_encoding=True)

    documents = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    texts = splitter.split_documents(documents)
    raw_texts = [t.page_content for t in texts]
    metadatas = [t.metadata for t in texts]

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    db = await HybridFAISSStore.from_texts(
        texts=raw_texts,
        embedding=embeddings,
        backend=store,
        use_memory_backend=True,
        metadatas=metadatas
    )

    retriever = await db.as_retriever()

    app.state.retriever_chain = RetrievalQA.from_chain_type(
        llm=llm, retriever=retriever
    )

    return JSONResponse({"message": "File uploaded and processed."})


@app.post("/query/")
async def query_route(request: Request):
    data = await request.json()
    question = data.get("question")

    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    retriever_chain = app.state.retriever_chain
    result = await retriever_chain.ainvoke(question)
    return JSONResponse({"answer": result["result"]})