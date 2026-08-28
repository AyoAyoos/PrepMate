# Build Log — Real File Upload + Multi-format Ingestion

Date: 2026-08-28

## Problem

The "ADD" button in the Ingest Source dialog did **not** upload files. It sent
a raw filename string to `POST /ingest`, and the backend only looked for that
file inside `Backend/data/pdfs/`. Unless the PDF already existed there, the
request returned `404 "PDF not found"`, so the button "didn't work".

## Goal

Make the ADD button open the OS file explorer (like ChatGPT), let the user pick
**multiple files** of **various readable types**, upload them, and index them
for retrieval.

## Changes

### Backend

**`Backend/src/ingest.py`**
- Added `SUPPORTED_EXTS` — the set of extensions the pipeline can parse:
  `.pdf .docx .txt .md .csv .xlsx .xls .log .json`.
- Replaced `resolve_pdf_files()` with `resolve_source_files()`, which matches
  *all* supported extensions (single file or a whole folder). Kept
  `resolve_pdf_files` as an alias so existing callers still work.
- Replaced `load_pdfs()` with `load_documents()` + a `_read_as_documents()`
  loader factory that dispatches by extension:
  - `.pdf`  -> `PyPDFLoader` (pypdf)
  - `.docx` -> `python-docx` (paragraph text)
  - `.xlsx`/`.xls` -> `openpyxl` (cell text rows)
  - `.txt/.md/.csv/.log/.json` -> plain text with encoding fallback (utf-8 -> latin-1)
- Loader failures on individual files are caught and logged without aborting
  the whole batch.
- Kept `load_pdfs` as an alias for backward compatibility.
- Kept the existing per-file dedup (name + content-hash) logic unchanged.

**`Backend/src/api.py`**
- Added `POST /ingest/upload` — a multipart endpoint that accepts one or more
  `UploadFile`s plus a `mode` (`append`/`clear`):
  1. Sanitizes each filename (strips directory traversal, `Path(name).name`).
  2. Validates extension against `SUPPORTED_EXTS`; unsupported files are
     skipped and reported.
  3. Writes each file into `Backend/data/pdfs/`.
  4. Runs the existing `ingest()` pipeline (append or clear).
  5. Returns the standard `IngestResponse` (documents + note).
- The old `POST /ingest` (by-filename) endpoint is preserved for back-compat.

**`Backend/requirements.txt`**
- Added `python-multipart` (required for FastAPI File/Form data),
  `python-docx`, and `openpyxl`.
- Installed all three into the project venv (`Backend/venv`).

**Note on dependencies:** I deliberately did **not** add the `unstructured`
package. Its loaders for PPTX/HTML are heavy and fragile to install. The chosen
loaders (pypdf / python-docx / openpyxl / stdlib text) cover the common
document types requested (PDF, DOCX, XLSX, TXT, MD, CSV) without the bloat.

### Frontend

**`Frontend/src/lib/api.ts`**
- Added `uploadSources(files: File[], mode)`:
  - Builds a `FormData` (`files` entries + `mode`).
  - POSTs to `/ingest/upload` as multipart (browser sets the boundary; no
    manual Content-Type).
  - Returns the same `IngestResponse`.
- Kept `ingestSource` (legacy by-filename) for back-compat.

**`Frontend/src/components/syllabus/IngestPanel.tsx`**
- Replaced the text `Input` + plain "Add" with a real **file picker** flow:
  - Hidden `<input type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.log,.json" multiple>`.
  - An **"Add files…"** button that opens the OS file explorer on click.
  - Selected files appear in a **pending list** with size and a remove (✕)
    button per file.
  - **"Add more"** lets you append more files; **"Upload N files"** runs
    `uploadSources(files, mode)` with the existing busy/spinner state.
  - Pending list clears after a successful upload.
- Kept the **Append (default)** / **Clear + reset** mode toggle and the
  **Clear vector store** button exactly as before.
- Kept the existing indexed-documents list below.
- Added basic error handling: upload/clear failures surface in the note area.

## Verification

- Backend modules import cleanly; `/ingest/upload` route is registered.
  (`python -c "from src import ingest, api; ..."` via `Backend/venv`.)
- Frontend builds successfully (`npm run build` in `Frontend/`).
- Optional full runtime test (actual upload + embedding) was skipped per user
  instruction; it requires Ollama + the Chroma store live.

## How to run

1. **Backend:** from `Backend/` run `.\venv\Scripts\python.exe -m src.api`
   (needs Ollama running for embeddings).
2. **Frontend:** from `Frontend/` run `npm run dev`.
3. Click **Ingest** (top-right), then **Add files…**, pick any supported file(s)
   from anywhere on your PC, then **Upload N files**.
