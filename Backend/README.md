# Ask-the-Syllabus Bot (RAG)

> **Working directory:** This backend lives in the `Backend/` folder. Run all
> `python -m ...` commands from inside `Backend/` (e.g. `cd Backend`) so the
> `src` / `eval` packages and relative paths (`data/pdfs`, `vectorstore/`, `.env`)
> resolve correctly.

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

5. **Ingest** the PDFs — see [Ingestion](#ingestion) below for the three modes:

   ```bash
   python -m src.ingest
   ```

6. **Run the bot** (interactive CLI):
   ```bash
   python -m src.cli
   ```

## HTTP API (FastAPI)

The backend also exposes the RAG pipeline over HTTP for the frontend
(`Frontend/`). Start it with:

```bash
python -m src.api        # serves http://localhost:8000
```

| Method | Path           | Purpose                                            |
|--------|----------------|----------------------------------------------------|
| GET    | `/documents`   | List source documents currently in the store       |
| POST   | `/ask`         | Ask a question → grounded answer + citations       |
| POST   | `/ingest`      | Append a PDF (or clear + re-ingest) by filename    |
| DELETE | `/documents`   | Wipe the vector store                              |
| GET    | `/health`      | Liveness check                                     |

Interactive docs (`swagger`) are at `http://localhost:8000/docs`.

The frontend calls these endpoints through `Frontend/src/lib/api.ts`. If the API
is not on `localhost:8000`, point the frontend at it with the `VITE_API_BASE`
env var, e.g.:

```bash
VITE_API_BASE=http://localhost:8000 bun dev   # from Frontend/
```

`/ingest` resolves the provided filename against `data/pdfs/` — a PDF must
already be present in that folder (or be added there) to ingest it.

## Ingestion

```
python -m src.ingest                                   # append data/pdfs/ (default)
python -m src.ingest --source path/to/folder           # append all PDFs in a folder
python -m src.ingest --source path/to/file.pdf         # append a single PDF
python -m src.ingest --clear [--source <path>]         # wipe the store, then ingest
python -m src.ingest --list                            # show which sources are stored
python -m src.ingest --analyze                         # chunk-only report (no embedding)
```

- **`--source <file-or-folder>`** — where to read PDFs from. Defaults to
  `data/pdfs/` (or the `.env` `PDF_DIR`). A single `.pdf` ingests just that
  file; a folder ingests every PDF inside it. The path must exist and contain
  at least one PDF, otherwise ingestion fails with a clear error.
- **Default = append.** New PDFs are added to whatever is already in the store,
  so a corpus can grow across sessions. Unit 1 and Unit 2 ingested today and
  Unit 3 tomorrow all remain searchable together:
  ```bash
  python -m src.ingest --source data/unit1   # day 1
  python -m src.ingest --source data/unit2   # day 2: unit1 + unit2 stored
  python -m src.ingest --source data/unit3   # day 3: unit1 + unit2 + unit3 stored
  ```
- **`--clear`** — wipes the existing collection completely *before* ingesting
  the given source. Use this to switch subjects/corpora entirely rather than
  add to the current one.
- **`--list`** — prints the source filenames currently represented in the
  store, so you can decide whether to append or clear.
- **Duplicate guard.** On append, each PDF is matched against the store by
  filename **and** a streaming content hash (`file_sha1`, stored in every
  chunk's metadata). A file already present is skipped with an explicit
  `Skipped: <name> (already in store, name + content-hash match)` line, so
  accidentally re-running ingestion on an already-added unit adds no duplicate
  chunks and can't skew retrieval.

The chunking, embedding, and citation-metadata logic is unchanged by these
modes — only *where* the chunks come from and *whether* the store is appended
or rebuilt differs.

## Evaluation (grounded vs hallucinated)

A fixed eval set lives in `eval/test_questions.json` — a mix of questions that
*should* be answerable from a syllabus and questions that are deliberately
out-of-domain (and therefore must be refused). Run:

```bash
python -m eval.run_eval
```

It reports per-question verdicts plus an overall accuracy metric:

```
Grounded answers:  5/5
Correct refusals:  3/3
Overall accuracy:  8/8 (100%)
```

Higher accuracy == fewer hallucinations. The eval only counts an answer as
*grounded* when it is backed by retrieved chunks with citations, and only
counts a refusal as *correct* when the model declined to guess.

## How retrieval reduces hallucination (jury Q1)

A bare LLM is a next-token predictor: when asked something it "kind of knows",
it can confidently fabricate plausible-but-wrong details (hallucination)
because it has no way to check against ground truth.

RAG fixes this by **conditioning the generation on retrieved evidence**:

1. **Constrain the source of truth** — the prompt tells the model to answer
   *only* from the provided context, and the retrieval step ensures that
   context actually comes from the course PDFs.
2. **Grounding forces faithfulness** — every claim the model makes must be
   traceable to a retrieved passage, and we surface those passages as
   citations so a human can verify. If the material isn't there, the model
   can't invent it.
3. **A relevance gate rejects weak evidence (Step 3)** — chunks whose L2
   distance exceeds `MAX_DISTANCE` are discarded (Chroma's score is a distance:
   *lower = more similar*), so the model is never asked to answer from
   barely-related text.
4. **Temperature 0** reduces random generation variance, so outputs stay close
   to what the context supports.

Net effect: the model's answer space is restricted to what the documents
actually say, which is precisely where a syllabus bot's answers must live.

## What happens when the answer isn't in the documents? (jury Q2)

Handling missing information is a **three-layer defense**, in order of
application inside `generate.py`:

1. **Retrieval distance gate (layer a).** Chunks whose L2 distance exceeds
   `MAX_DISTANCE` are rejected *before* the LLM is ever called. If nothing
   survives, we return a fixed refusal ("I could not find the answer to this
   question in the course documents.") marked **not grounded** — no guess.
2. **Prompt-side refusal instruction (layer b).** The system prompt tells the
   model to emit a fixed literal marker — `"This isn't covered in the provided
   materials."` — whenever the context doesn't actually answer the question,
   rather than hedging into a partial guess.
3. **Output-side marker detection (layer c).** After generation, `generate()`
   scans the model output for that marker and flips `grounded=False` even when
   chunks passed the gate. This catches the hardest RAG case: retrieval *did*
   return relevant-ish chunks, but none of them actually answer the specific
   question. In the CLI, those chunks are still shown, labeled
   "considered but insufficient."

Layers (b)+(c) use a fixed, literal marker so the refusal is *detectable*, not
just "something refusal-ish." Detection is case-insensitive and tolerant of
trailing punctuation. Together the three layers answer "how do you prevent
hallucination on absent information" with concrete, testable mechanisms.

In the eval, such questions are expected to be `unanswerable`, and `run_eval.py`
trusts `Answer.grounded` (from the three layers) — so both the distance-gate
refusal and the marker-detected refusal score as a *correct refusal*. Refusing
is the right outcome, not a failure.

## Project layout

```
ask-the-syllabus-bot/
├── data/pdfs/                # your source syllabus/course PDFs go here
├── src/
│   ├── config.py             # shared env-driven configuration
│   ├── ingest.py             # PDF -> chunks -> embed -> Chroma
│   ├── retrieve.py           # embed query, similarity search
│   ├── generate.py           # prompt + Ollama + relevance gate
│   ├── citations.py          # chunk metadata -> readable citations
│   └── cli.py                # interactive Q&A loop
├── eval/
│   ├── test_questions.json   # fixed eval set
│   └── run_eval.py           # runs eval, reports grounded vs hallucinated
├── vectorstore/              # Chroma's persisted DB (gitignored)
├── .env                      # OLLAMA_HOST, model names, thresholds (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Demo script (for the presentation)

1. Show the corpus PDFs in `data/pdfs/`.
2. `python -m src.ingest` — briefly comment on chunking (size/overlap) and the
   embedding model.
3. `python -m src.cli` and ask:
   - A syllabus question → grounded answer with `[1] ...` citations.
   - The exact same out-of-domain question from the eval set → graceful refusal.
4. `python -m eval.run_eval` — show the grounded-vs-hallucinated metric.
5. Explain the architecture diagram and the two jury answers above.

## Known limitations

- **Image-based slides are not retrievable.** 25/181 pages are image-based
  slides (diagrams, charts, section dividers) with no extractable text; they
  are not covered by retrieval without OCR. pypdf text-extraction currently
  ignores them, so questions whose answer lives only in a diagram will be
  answered as "not found."
- **Shadow/duplicate text glyphs.** A small number of slides carry
  unselected/duplicated glyph fragments (e.g. "parsingis" for "parsing is")
  from the source PDF. Cosmetic only — it does not affect retrieval.
