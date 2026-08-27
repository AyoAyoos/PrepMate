"""Step 1 of the RAG pipeline: ingest PDFs.

Loads PDFs, splits each page into overlapping chunks, embeds them with
OllamaEmbeddings, and persists them in a local Chroma vector store so that
retrieval (Step 2) can search them later.

--source selects where the PDFs are read from (default data/pdfs/).

--analyze runs the load + split stages only (no embedding, no store writes) and
prints a diagnostic report on how the corpus chunks — useful for tuning
CHUNK_SIZE/CHUNK_OVERLAP before paying for a full embed pass.
"""
from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    OLLAMA_EMBED_MODEL,
    OLLAMA_HOST,
    SOURCE_DEFAULT,
    VECTORSTORE_DIR,
)


def _source_files(source: Path) -> list[Path]:
    """Glob PDFs in the source directory (folder ingest)."""
    return sorted(source.glob("*.pdf"))


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


def _embed_chunks(chunks: list) -> None:
    """Embed and persist chunks into the Chroma store."""
    embeddings = OllamaEmbeddings(
        base_url=OLLAMA_HOST,
        model=OLLAMA_EMBED_MODEL,
    )
    vectorstore = Chroma(
        persist_directory=str(VECTORSTORE_DIR),
        embedding_function=embeddings,
    )
    if chunks:
        vectorstore.add_documents(chunks)


def ingest(source: Path) -> None:
    """Load, split, embed, and persist PDFs from the given source folder."""
    files = _source_files(source)
    documents = load_pdfs(files)
    chunks, oversized = split_documents(documents)
    pages = len(documents)
    print(f"Pages: {pages} | Chunks: {len(chunks)} | "
          f"Slides over {CHUNK_SIZE} chars split: {oversized}")
    print(f"Ratio: ~{len(chunks) / max(pages, 1):.2f} chunks per page")

    _embed_chunks(chunks)
    print(f"Added {pages} pages / {len(chunks)} chunks "
          f"from {len(files)} file(s) to store at {VECTORSTORE_DIR}")


def analyze(source: Path) -> None:
    """Split-only diagnostic: report chunking without embedding."""
    files = _source_files(source)
    documents = load_pdfs(files)
    if not documents:
        return

    chunks, oversized = split_documents(documents)
    print(f"\nPages: {len(documents)} / {len(files)} file(s)")
    print(f"Chunks: {len(chunks)}  (oversized slides split: {oversized})")
    print(f"Ratio: ~{len(chunks) / max(len(documents), 1):.2f} chunks per page\n")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " "],
    )
    for d in documents:
        if len(d.page_content) > CHUNK_SIZE:
            sub = splitter.split_text(d.page_content)
            print(f"  Split slide: {d.metadata.get('source')} page {d.metadata.get('page')} "
                  f"({len(d.page_content)} chars -> {len(sub)} sub-chunks)")


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.ingest",
        description="Ingest course PDFs into the Chroma vector store.",
    )
    parser.add_argument(
        "--source",
        default=str(SOURCE_DEFAULT),
        help=f"PDF folder to ingest. Default: {SOURCE_DEFAULT}",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Only split + report chunking (no embedding, no store changes).",
    )
    args = parser.parse_args()

    source = Path(args.source)
    if args.analyze:
        analyze(source)
    else:
        ingest(source)


if __name__ == "__main__":
    _cli()
