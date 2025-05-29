"""Main FastAPI application for document upload and QA via LangChain."""

import shutil
from pathlib import Path

from fastapi import FastAPI, Request, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.text_splitter import RecursiveCharacterTextSplitter

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_ollama.llms import OllamaLLM

app = FastAPI()
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = Path("uploads")
app.state.retriever_chain = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the index page."""
    return templates.TemplateResponse("chatui/index.html", {"request": request})


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    """Handle file upload and initialize the retriever."""
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

    embeddings = HuggingFaceEmbeddings()
    db = FAISS.from_documents(texts, embeddings)

    app.state.retriever_chain = RetrievalQA.from_chain_type(
        llm=OllamaLLM(model="gemma3:4b"), retriever=db.as_retriever()
    )

    return JSONResponse({"message": "File uploaded and processed."})


@app.post("/query/")
async def ask_question(request: Request):
    """Process a question against the uploaded document."""
    if not app.state.retriever_chain:
        return JSONResponse({"error": "No document uploaded yet."}, status_code=400)

    data = await request.json()
    question = data.get("question", "")
    answer = app.state.retriever_chain.run(question)
    return JSONResponse({"answer": answer})
