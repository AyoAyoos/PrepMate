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

Subprojects:

- **`Backend/`** — Python RAG pipeline (`src/ingest.py`, `src/retrieve.py`,
  `src/generate.py`, `src/cli.py`), a FastAPI HTTP layer (`src/api.py`), and the
  `eval/` harness. See [Backend/README.md](Backend/README.md).
- **`Frontend/`** — React/TanStack chat interface (source in `Frontend/src/`),
  consuming the backend API at `src/lib/api.ts`.

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
[Backend/README.md](Backend/README.md).

## Quick start (frontend)

From `Frontend/`:

```bash
npm install        # or: bun install
npm run dev        # starts the chat UI (Vite dev server)
```

Open the printed URL in a browser, add course documents via **Ingest** (top
right), and ask questions in the chat. The UI talks to the backend at
`http://localhost:8000` by default; if the API is served elsewhere, point the
UI at it with the `VITE_API_BASE` env var:

```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```

Other checks:

```bash
npm run lint       # ESLint
npm run build      # production build
```
