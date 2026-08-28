# PrepMate — Ask-the-Syllabus Bot

A Retrieval-Augmented Generation (RAG) Q&A system over course/syllabus PDFs. Ask
a question and it answers **exclusively from retrieved context** with readable
source citations, refusing rather than hallucinating when nothing relevant is
found.

## Project layout

```
PrepMate/
├── Backend/    Python RAG backend (ingest → retrieve → generate + eval)
├── Frontend/   React + TypeScript frontend (chat UI over the backend)
```

Each subfolder has its own README with full setup and usage:

- **[Backend/README.md](Backend/README.md)** — Python RAG pipeline: `src/ingest.py`,
  `src/retrieve.py`, `src/generate.py`, `src/cli.py`, plus the `eval/` harness.
  Run all `python -m ...` commands from inside `Backend/`.
- **[Frontend/README.md](Frontend/README.md)** — React/TanStack chat interface.

## Quick start (backend)

From `Backend/`:

```bash
pip install -r requirements.txt   # Python 3.10+
cp .env.example .env              # then adjust model names as needed
ollama pull llama3.2              # chat / generation model
ollama pull nomic-embed-text      # embedding model
python -m src.ingest              # ingest data/pdfs/*.pdf once
python -m src.cli                 # start the chat bot
```

For the end-to-end flow, detailed options, and evaluation, see
[Backend/README.md](Backend/README.md) and
[manual.md](Backend/manual.md).
