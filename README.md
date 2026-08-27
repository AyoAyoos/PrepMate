# Ask-the-Syllabus Bot (RAG)

A Retrieval-Augmented Generation (RAG) Q&A demo over course/syllabus PDFs.
Given a question, it retrieves the most relevant passages from your course
documents and answers **exclusively from that retrieved context**, printing
readable source citations. If nothing relevant is found, it refuses to answer
rather than hallucinate.

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │                    OLLAMA                    │
                    │   embeddings model  +  chat/LLM model        │
                    └──────────────────────────────────────────────┘
        Step 1 (once)        │                          │        Step 3 (per Q)
 ┌───────────────┐   embed   │                          │   generate
 │ data/pdfs/*.pdf ───▶ chunks ──▶ Chroma (vectorstore/)       │
 │  ingest.py    │  load/split/embed     ▲                      │
 └───────────────┘                       │ similarity search    │
                    Step 2 (per Q)  ─────┘   retrieve.py        ▼
                    question ──▶ embed ──▶ top-k chunks ──▶ prompt ─▶ answer
                                                       └──▶ citations.py
```

- **Step 1 — Ingest (`src/ingest.py`)** loads every PDF, splits it into
  overlapping text chunks, embeds the chunks, and persists them to a local
  Chroma store. Runs *once* (or whenever documents change).
- **Step 2 — Retrieve (`src/retrieve.py`)** embeds the question with the same
  model and does a similarity search to pull the top-k chunks. Runs *per question*.
- **Step 3 — Generate (`src/generate.py`)** checks each retrieved chunk against
  a similarity gate, builds a grounding prompt ("answer only from this
  context"), calls Ollama at temperature 0, and returns the answer.
- **Citations (`src/citations.py`)** turns chunk metadata (source file, page,
  similarity score) into readable `[1] syllabus.pdf — p.3 (sim 0.82)` lines,
  making the grounding explicit to the user.
- **CLI (`src/cli.py`)** is an interactive loop that glues Steps 2–3 together.

### Why ingest and query are separate scripts
Ingestion and querying run at different frequencies with different lifetimes:
you ingest rarely (once per document set) but query constantly. This is a real
RAG design principle — you persist the expensive embeddings once and reuse them,
instead of re-embedding the corpus on every question.

### Why citations.py is its own module
Citation generation is a distinct concern from prompt construction. Keeping it
separate communicates that surfacing provenance is a first-class part of the
design, not an afterthought bolted into the prompt string.

## Setup

1. **Install Ollama** and pull the models used in `.env`:
   ```bash
   ollama pull llama3.2       # chat / generation model
   ollama pull nomic-embed-text  # embedding model
   ```
   (Start the Ollama server: `ollama serve`.)

2. **Install Python dependencies** (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   ```

3. **Drop your course PDFs** into `data/pdfs/`.

4. **Configure** — copy `.env.example` to `.env` and adjust model names,
   `RETRIEVE_K`, and `MAX_DISTANCE` if desired.

5. **Ingest** the PDFs:
   ```bash
   python -m src.ingest
   ```

6. **Run the bot**:
   ```bash
   python -m src.cli
   ```
