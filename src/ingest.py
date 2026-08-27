"""Step 1 of the RAG pipeline: ingest PDFs.

Loads PDFs and splits each page into chunks with RecursiveCharacterTextSplitter
so later steps can embed and store them. Chunking keeps each slide semantically
atomic while still splitting any dense slide that exceeds the chunk size.
"""
from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import CHUNK_OVERLAP, CHUNK_SIZE


def load_pdfs(files: list[Path]) -> list:
    """Load PDF files into LangChain documents (one per page)."""
    documents = []
    for pdf in files:
        print(f"Loading {pdf.name} ...")
        loader = PyPDFLoader(str(pdf))
        pages = loader.load()
        for page in pages:
            page.metadata["source"] = pdf.name
        documents.extend(pages)
    return documents


def split_documents(documents: list) -> tuple:
    """Split loaded page documents into chunks.

    Returns (chunks, per_page_over_CHUNK_SIZE) where the second value is the
    count of pages that exceeded CHUNK_SIZE and had to be split.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)
    oversized = sum(1 for d in documents if len(d.page_content) > CHUNK_SIZE)
    return chunks, oversized


def ingest(files: list[Path]) -> None:
    """Split the files and report chunking stats (no embedding yet)."""
    documents = load_pdfs(files)
    chunks, oversized = split_documents(documents)
    print(f"Pages: {len(documents)} | Chunks: {len(chunks)} | "
          f"Slides over {CHUNK_SIZE} chars split: {oversized}")
    print(f"Ratio: ~{len(chunks) / max(len(documents), 1):.2f} chunks per page")
