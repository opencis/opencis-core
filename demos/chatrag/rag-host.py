"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

#!/usr/bin/env python

import asyncio
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama.llms import OllamaLLM

from memory_backend import AlignedMemoryBackend, StructuredMemoryAdapter
from memory_vector_search import MemoryVectorSearch

from opencis.cpu import CPU
from opencis.cxl.component.cxl_host import CxlHost, CxlHostConfig
from opencis.cxl.component.cxl_memory_hub import CxlMemoryHub, MEM_ADDR_TYPE
from opencis.drivers.cxl_bus_driver import CxlBusDriver
from opencis.drivers.cxl_mem_driver import CxlMemDriver
from opencis.drivers.pci_bus_driver import PciBusDriver
from opencis.util.logger import logger
from opencis.util.number_const import MB


@dataclass
class AppConfig:
    pci_cfg_base_addr: int = 0x10000000
    pci_cfg_size: int = 0x10000000
    pci_mmio_base_addr: int = 0xFE000000
    cxl_hpa_base_addr: int = 0x100000000000
    sys_mem_base_addr: int = 0xFFFF888000000000
    sys_mem_size: int = 2 * MB
    cxl_port_index: int = 0
    fastapi_port: int = 9000
    ollama_model: str = "gemma3:4b"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


class CxlMemoryBackend:
    def __init__(self, cpu: CPU, base_addr: int):
        self.cpu = cpu
        self.base_addr = base_addr

    def set_base_addr(self, addr: int):
        self.base_addr = addr

    async def load(self, addr: int, size: int) -> int:
        addr += self.base_addr
        return await self.cpu.load(addr, size)

    async def store(self, addr: int, size: int, value: int):
        addr += self.base_addr
        await self.cpu.store(addr, size, value)


async def my_sys_sw_app(**kwargs):
    cxl_memory_hub: CxlMemoryHub = kwargs["cxl_memory_hub"]
    config = AppConfig()

    pci_bus_driver = PciBusDriver(cxl_memory_hub.get_root_complex())
    await pci_bus_driver.init(config.pci_mmio_base_addr)

    for i, device in enumerate(pci_bus_driver.get_devices()):
        cxl_memory_hub.add_mem_range(
            config.pci_cfg_base_addr + (i * config.pci_cfg_size),
            config.pci_cfg_size,
            MEM_ADDR_TYPE.CFG,
        )
        for bar in device.bars:
            if bar.base_address:
                cxl_memory_hub.add_mem_range(bar.base_address, bar.size, MEM_ADDR_TYPE.MMIO)

    cxl_bus_driver = CxlBusDriver(pci_bus_driver, cxl_memory_hub.get_root_complex())
    cxl_mem_driver = CxlMemDriver(cxl_bus_driver, cxl_memory_hub.get_root_complex())
    await cxl_bus_driver.init()
    await cxl_mem_driver.init()

    hpa_base = config.cxl_hpa_base_addr
    for device in cxl_mem_driver.get_devices():
        size = device.get_memory_size()
        success = await cxl_mem_driver.attach_single_mem_device(device, hpa_base, size)
        if success:
            cxl_memory_hub.add_mem_range(hpa_base, size, MEM_ADDR_TYPE.CXL_UNCACHED)
            hpa_base += size

    sys_mem_size = cxl_memory_hub.get_root_complex().get_sys_mem_size()
    cxl_memory_hub.add_mem_range(config.sys_mem_base_addr, sys_mem_size, MEM_ADDR_TYPE.DRAM)

    for r in cxl_memory_hub.get_memory_ranges():
        logger.info(
            f"[SYS-SW] MemoryRange: base: 0x{r.base_addr:X}, "
            f"size: 0x{r.size:X}, type: {r.addr_type}"
        )


def create_langchain_app(cpu: CPU) -> FastAPI:
    config = AppConfig()
    backend = CxlMemoryBackend(cpu, config.cxl_hpa_base_addr)
    aligned = AlignedMemoryBackend(backend.load, backend.store)
    store = StructuredMemoryAdapter(aligned)

    llm = OllamaLLM(model=config.ollama_model)
    embedding_model = HuggingFaceEmbeddings(model_name=config.embedding_model)
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
    config = uvicorn.Config(app, host="0.0.0.0", port=AppConfig().fastapi_port, loop="asyncio")
    server = uvicorn.Server(config)

    t = asyncio.create_task(server.serve())
    await asyncio.gather(t)


async def main():
    sw_portno = int(sys.argv[1])

    cxl_host_config = CxlHostConfig(
        port_index=AppConfig().cxl_port_index,
        sys_mem_size=AppConfig().sys_mem_size,
        user_app=my_user_app,
        sys_sw_app=my_sys_sw_app,
        host_name="LangchainHost",
        switch_port=sw_portno,
        enable_hm=False,
    )
    host = CxlHost(cxl_host_config)
    host_task = asyncio.create_task(host.run())
    await host_task


if __name__ == "__main__":
    asyncio.run(main())
