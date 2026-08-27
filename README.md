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
