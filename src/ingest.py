"""Step 1 of the RAG pipeline: ingest PDFs.

This first pass only loads PDF files into LangChain page documents and tags
each page so we know which source file it came from. Chunking and embedding
are added in later steps.
"""
from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader


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
