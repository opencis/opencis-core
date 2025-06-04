"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

#!/usr/bin/env python

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

import click
import uvicorn
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import PyPDFLoader, TextLoader

from opencis.cpu import CPU
from opencis.cxl.component.cxl_host import CxlHost, CxlHostConfig
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, MEM_ADDR_TYPE
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.util.logger import logger
from opencis.util.number_const import MB
from opencis.apps.backend.memory_backend import (
    AlignedMemoryBackend,
    StructuredMemoryAdapter,
)
from demos.chatrag.memory_vector_search import MemoryVectorSearch


@dataclass
class AppConfig:
    pci_cfg_base_addr: int = 0x10000000
    pci_cfg_size: int = 0x10000000
    pci_mmio_base_addr: int = 0xFE000000
    cxl_hpa_base_addr: int = 0x100000000000
    sys_mem_base_addr: int = 0xFFFF888000000000
    sys_mem_size: int = 2 * MB
    cxl_port_index: int = 0
    switch_port: int = 8000
    fastapi_port: int = 9000
    model_name: str = "gemma3:4b"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    llm_source: str = "ollama"
    api_token: str = ""


app_config = AppConfig()


def get_llm():
    # pylint: disable=import-outside-toplevel
    source = app_config.llm_source
    model = app_config.model_name

    if source == "ollama":
        from langchain_ollama.llms import OllamaLLM

        return OllamaLLM(model=model)

    if source == "huggingface":
        from langchain.llms import huggingface_hub

        return huggingface_hub.HuggingFaceHub(
            repo_id=model, huggingfacehub_api_token=app_config.api_token
        )

    if source == "openai":
        from langchain.llms import openai

        return openai.OpenAI(model_name=model, openai_api_key=app_config.api_token)

    if source == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, google_api_key=app_config.api_token)

    raise ValueError(f"Unsupported LLM source: {source}")


async def my_sys_sw_app(**kwargs):
    cxl_memory_hub: CxlMemoryHub = kwargs["cxl_memory_hub"]

    pci_bus_driver = PciBusDriver(cxl_memory_hub.get_root_complex())
    await pci_bus_driver.init(app_config.pci_mmio_base_addr)

    for i, device in enumerate(pci_bus_driver.get_devices()):
        cxl_memory_hub.add_mem_range(
            app_config.pci_cfg_base_addr + (i * app_config.pci_cfg_size),
            app_config.pci_cfg_size,
            MEM_ADDR_TYPE.CFG,
        )
        for bar in device.bars:
            if bar.base_address:
                cxl_memory_hub.add_mem_range(bar.base_address, bar.size, MEM_ADDR_TYPE.MMIO)

    cxl_bus_driver = CxlBusDriver(pci_bus_driver, cxl_memory_hub.get_root_complex())
    cxl_mem_driver = CxlMemDriver(cxl_bus_driver, cxl_memory_hub.get_root_complex())
    await cxl_bus_driver.init()
    await cxl_mem_driver.init()

    hpa_base = app_config.cxl_hpa_base_addr
    for device in cxl_mem_driver.get_devices():
        size = device.get_memory_size()
        success = await cxl_mem_driver.attach_single_mem_device(device, hpa_base, size)
        if success:
            cxl_memory_hub.add_mem_range(hpa_base, size, MEM_ADDR_TYPE.CXL_UNCACHED)
            hpa_base += size

    sys_mem_size = cxl_memory_hub.get_root_complex().get_sys_mem_size()
    cxl_memory_hub.add_mem_range(app_config.sys_mem_base_addr, sys_mem_size, MEM_ADDR_TYPE.DRAM)

    for r in cxl_memory_hub.get_memory_ranges():
        logger.info(
            f"[SYS-SW] MemoryRange: base: 0x{r.base_addr:X}, "
            f"size: 0x{r.size:X}, type: {r.addr_type}"
        )


def create_langchain_app(cpu: CPU) -> FastAPI:
    aligned = AlignedMemoryBackend(cpu.load, cpu.store, app_config.cxl_hpa_base_addr)
    store = StructuredMemoryAdapter(aligned)

    llm = get_llm()
    embedding_model = HuggingFaceEmbeddings(model_name=app_config.embedding_model)
    retriever = MemoryVectorSearch(store, embedding_model)

    retriever_chain = RetrievalQA.from_chain_type(llm=llm, retriever=retriever)

    app = FastAPI()
    app.state.retriever_chain = retriever_chain
    templates = Jinja2Templates(directory="templates")
    UPLOAD_DIR = Path("uploads")

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
        loader = (
            PyPDFLoader(str(file_path))
            if ext == ".pdf"
            else TextLoader(str(file_path), encoding="utf-8")
        )
        documents = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(documents)

        await retriever.add_documents(chunks)
        return JSONResponse({"message": "File uploaded and processed."})

    @app.delete("/upload/")
    async def delete_uploaded_files():
        if UPLOAD_DIR.exists():
            for file in UPLOAD_DIR.iterdir():
                if file.is_file():
                    file.unlink()
            return JSONResponse({"message": "All uploaded files deleted."})
        return JSONResponse({"message": "Upload directory does not exist."})

    @app.post("/query/")
    async def query_route(request: Request):
        data = await request.json()
        question = data.get("question")
        if not question:
            return JSONResponse({"error": "No question provided"}, status_code=400)
        result = await retriever_chain.ainvoke(question)
        return JSONResponse({"answer": result["result"]})

    return app


async def my_user_app(**kwargs):
    cpu: CPU = kwargs["cpu"]
    app = create_langchain_app(cpu)
    config = uvicorn.Config(app, host="0.0.0.0", port=app_config.fastapi_port, loop="asyncio")
    server = uvicorn.Server(config)

    t = asyncio.create_task(server.serve())
    await asyncio.gather(t)


async def main():
    cxl_host_config = CxlHostConfig(
        port_index=app_config.cxl_port_index,
        sys_mem_size=app_config.sys_mem_size,
        user_app=my_user_app,
        sys_sw_app=my_sys_sw_app,
        host_name="LangchainHost",
        switch_port=app_config.switch_port,
        enable_hm=False,
    )
    host = CxlHost(cxl_host_config)
    host_task = asyncio.create_task(host.run())
    await host_task


@click.command()
@click.option("--switch_port", default=8000, type=int, help="CXL Switch port")
@click.option("--server-port", default=9000, type=int, help="Port to run the FastAPI server on.")
@click.option(
    "--llm-source",
    type=click.Choice(["ollama", "huggingface", "openai", "gemini"], case_sensitive=False),
    default="ollama",
    help="Choose LLM provider: 'ollama', 'huggingface', 'openai', or 'gemini'.",
)
@click.option("--api-token", type=str, default="", help="API token for remote LLM provider")
@click.option("--model-name", type=str, default="gemma3:4b", help="Name of the model to use")
def cli(switch_port, server_port, llm_source, api_token, model_name):
    app_config.fastapi_port = server_port
    app_config.llm_source = llm_source.lower()
    app_config.api_token = api_token
    app_config.switch_port = switch_port
    app_config.model_name = model_name
    asyncio.run(main())


if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
