# Ask-the-Syllabus Bot — User Manual

An end-to-end RAG chatbot that answers questions **from your course PDFs**
(never from outside knowledge), with per-page citations and a safety net that
refuses to guess when the answer isn't in the documents.

This manual covers how to get it running and how to use it day to day.

---

## 1. Before you start (one-time setup)

### 1.1 Prerequisites
- **Python 3.10+** installed.
- **Ollama** installed with the two models used by the bot:
  ```bash
  ollama pull llama3.2          # generates the answers
  ollama pull nomic-embed-text  # embeds text for search
  ```
- The Python dependencies installed (from the project folder):
  ```bash
  pip install -r requirements.txt
  ```
  > If you use the project's own virtual environment (recommended), activate it
  > first, e.g. on Windows: `venv\Scripts\activate`, then install with pip.

### 1.2 The environment file
Copy the template to a real config and check the defaults:
```bash
copy .env.example .env     # Windows
# cp .env.example .env     # macOS / Linux
```
The defaults are fine for a local setup. The important settings:

| Setting | What it controls |
|---|---|
| `OLLAMA_HOST` | Where Ollama is running (`http://localhost:11434`) |
| `OLLAMA_EMBED_MODEL` | Embedding model (`nomic-embed-text`) |
| `OLLAMA_LLM_MODEL` | Answering model (`llama3.2`) |
| `RETRIEVE_K` | How many chunks are pulled per question (4) |
| `MAX_DISTANCE` | Relevance gate — chunks farther than this are ignored (0.70) |
| `PDF_DIR` | Default folder to read PDFs from (`data/pdfs`) |
| `VECTORSTORE_DIR` | Where the search index lives (`vectorstore/chroma`) |

> ⚠️ If you ever change `OLLAMA_EMBED_MODEL`, you must **re-ingest** (rebuild
> the index) — see `--clear` below — or searches will silently mismatch.

### 1.3 Start Ollama
Keep Ollama running in a separate terminal:
```bash
ollama serve
```
(If you started Ollama as a desktop app, it's already running.)

---

## 2. Put your PDFs in place

By default the bot reads from the `data/pdfs/` folder:
```bash
data/pdfs/
├── Unit_I NLP.pdf
└── Unit II (1).pdf
```
You can drop as many course PDFs there as you like (one per unit, one whole
syllabus, etc.).

---

## 3. Ingest the PDFs (build the search index)

Ingestion reads the PDFs, splits them into one-chunk-per-slide, embeds them,
and stores them in `vectorstore/`. Run it from the **project root**:

```bash
python -m src.ingest                 # append data/pdfs/ (default)
```

You should see output like:
```
Pages: 181 | Chunks: 156 | Slides over 1000 chars split: 0
Ratio: ~0.86 chunks per page
Added 181 pages / 156 chunks from 2 file(s) to 'langchain' in ...\vectorstore\chroma
```

### 3.1 All ingestion modes

| Command | What it does |
|---|---|
| `python -m src.ingest` | Append `data/pdfs/` to the index (default) |
| `python -m src.ingest --source path/to/folder` | Append every PDF in a folder |
| `python -m src.ingest --source path/to/file.pdf` | Append a single PDF |
| `python -m src.ingest --clear` | Wipe the whole index, then ingest `data/pdfs/` |
| `python -m src.ingest --clear --source path/to/folder` | Wipe, then ingest that folder |
| `python -m src.ingest --list` | Show which source PDFs are already indexed |
| `python -m src.ingest --analyze` | Show chunking stats without writing to the index |

### 3.2 Adding content over time (the normal workflow)

**Default is append**, so you can grow your corpus across sessions and all
units stay searchable together:

```bash
python -m src.ingest --source data/unit1   # day 1
python -m src.ingest --source data/unit2   # day 2: unit1 + unit2
python -m src.ingest --source data/unit3   # day 3: unit1 + unit2 + unit3
```

**Starting over / switching subjects** — use `--clear` to remove everything
and index only the new source:
```bash
python -m src.ingest --clear --source path/to/new_subject
```

**Checking what's in the index** before deciding:
```bash
python -m src.ingest --list
# Source files currently in the vector store:
#   - Unit II (1).pdf
#   - Unit_I NLP.pdf
```

### 3.3 Duplicates
If a PDF is already in the index (matching by filename **and** content hash),
re-ingesting it is skipped — you'll see:
```
Skipped: Unit_I NLP.pdf (already in store, name + content-hash match)
Nothing new to ingest from D:\GEN_AI\PrepMate\data\pdfs.
```
So accidentally re-running ingestion never duplicates chunks.

---

## 4. Ask questions (the chatbot)

With content ingested and Ollama running, start the interactive session:

```bash
python -m src.cli
```

Sample session:
```
Ask-the-Syllabus Bot (RAG)
--------------------------
Ingest your course PDFs first with:  python -m src.ingest
Type a question, or 'quit' to exit.

You: What is stopword removal?

--- ANSWER ---
Stopword removal is the process of removing the most commonly occurring words
in a text that do not provide valuable information.

--- SOURCES ---
  [1] Unit_I NLP.pdf — p.41 (d=0.40)

You: What is the capital of France?

--- ANSWER ---
I could not find the answer to this question in the course documents.

(Not grounded: No retrieved content was sufficiently relevant to ground an
answer, so I am declining to answer rather than risk hallucinating.)

You: quit
Goodbye.
```

### 4.1 How to read the output
- **`--- ANSWER ---`** — the bot's answer.
- **`--- SOURCES ---`** — the slides it used, with:
  - the **source file** (`Unit_I NLP.pdf`),
  - the **page** (`p.41`),
  - the **distance** (`d=0.40`) — lower = more similar/relevant.
- **`(Not grounded: ...)`** — the bot decided it couldn't confidently answer.
  Two flavors:
  - *"No retrieved content was sufficiently relevant..."* → nothing near the
    question was found (out-of-scope question).
  - *"SOURCES (considered but insufficient)"* + the marker reply
    `"This isn't covered in the provided materials."` → it *found* related
    slides but none actually answered the question.

### 4.2 Exit commands
Type `quit`, `exit`, or `q`. (`Ctrl+C` / `Ctrl+Z` also ends the session.)

---

## 5. Run the evaluation

To measure how well the bot grounds answers vs. hallucinating:

```bash
python -m eval.run_eval
```

It runs a fixed question set over three categories and prints two results:
- **Layer 1** — does the bot's grounded/refused flag match expectation?
- **Layer 2** — faithfulness of each answer, plus an automated tripwire that
  flags any number in the answer that doesn't appear in the cited slides.

Example output:
```
Layer 1 accuracy: 13/13 (100%)
Automated faithfulness tripwire fired on 1/9 answerable answers.
```

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Retrieval failed (is Ollama running?): ...` | Start Ollama (`ollama serve`) or check `OLLAMA_HOST` in `.env` |
| `No module named 'src'` | You're not in the project root. `cd` into the project first |
| `ModuleNotFoundError: No module named 'langchain...'` | Run `pip install -r requirements.txt` (or activate the venv) |
| `The vector store is empty. Run python -m src.ingest first.` | No PDFs indexed yet — run `python -m src.ingest` |
| `ERROR: Source path does not exist: ...` | The `--source` path is wrong |
| `ERROR: No PDF files found at: ...` | The folder has no `.pdf` files |
| `Model ... not found` from Ollama | You haven't pulled the model: `ollama pull llama3.2` / `ollama pull nomic-embed-text` |
| Answers don't match after changing the embedding model | Rebuild the index: `python -m src.ingest --clear` |

---

## 7. Quick reference (all commands)

```bash
# Setup
pip install -r requirements.txt
ollama pull llama3.2
ollama pull nomic-embed-text
ollama serve

# Ingest
python -m src.ingest
python -m src.ingest --source myfile.pdf
python -m src.ingest --source myfolder/
python -m src.ingest --clear [--source ...]
python -m src.ingest --list
python -m src.ingest --analyze

# Chat
python -m src.cli

# Evaluate
python -m eval.run_eval
```

All commands run from the **project root** (`D:\GEN_AI\PrepMate`).
