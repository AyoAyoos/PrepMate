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

## Additional scaffolding (landed as separate commits)

Beyond the core feature, the following genuine improvements were added and each
committed separately:

- **Per-file size limit (backend)** — `MAX_UPLOAD_MB` in `src/config.py`
  (default 50 MB); oversized uploads are rejected and cleaned up.
- **Empty-file rejection (backend)** — files that land as zero bytes are
  skipped with a clear message.
- **Structured upload breakdown (backend + frontend)** — `IngestResponse` now
  carries `uploaded`, `duplicates`, and `skipped`, surfaced in the UI as a
  colour-coded summary.
- **Client-side validation (frontend)** — unsupported types, oversized files,
  and empty files are rejected before upload with friendly messages.
- **Filename collision handling (backend)** — two files with the same name in a
  batch (or colliding with disk) are written as `name_1.ext`, `name_2.ext`,
  etc. via `_unique_dest`.
- **Drag-and-drop selection (frontend)** — files can be dropped onto the
  Ingest dialog instead of only picked via the explorer.
- **Dependency additions** — `python-docx`, `openpyxl`, and `python-multipart`
  (installed into `Backend/venv`); intentionally avoided the heavy/fragile
  `unstructured` package.
- **Unit tests (backend)** — `Backend/tests/` covers loader dispatch and the
  filename-collision helper, runnable with stdlib `unittest` (no Ollama/Chroma
  needed): `python -m unittest discover -s tests -v`.
- **Docs** — `Backend/README.md` updated to document `/ingest/upload` and the
  supported file types.

## Verification

- Backend modules import cleanly; `/ingest/upload` route is registered.
  (`python -c "from src import ingest, api; ..."` via `Backend/venv`.)
- Backend unit tests pass: `python -m unittest discover -s tests -v` → 10 OK.
- Frontend builds successfully (`npm run build` in `Frontend/`).
- Optional full runtime test (actual upload + embedding) was skipped per user
  instruction; it requires Ollama + the Chroma store live.

## Commit log

The work was delivered as 16 self-contained commits on `main` (each was verified
to build/import before committing):

```
37f178b chore: ignore runtime uvicorn logs
e878330 chore(frontend): track package-lock.json generated by npm install
d977600 docs: add build log for real file upload and multi-format ingest
cda385a build(backend): add deps for multi-format uploads
b51520c feat(backend): support multi-format document loaders
b8f68d1 feat(backend): add POST /ingest/upload multipart endpoint
660ed65 feat(frontend): add uploadSources API helper
81a627a feat(frontend): rework ingest panel into a multi-file picker
3ee9061 feat(backend): enforce per-file upload size limit and reject empty files
7686755 feat: report per-file upload breakdown (added/duplicates/skipped)
7392322 feat(frontend): validate file type and size client-side before upload
3a3deab feat(backend): avoid filename collisions within an upload batch
4299438 docs(backend): document upload endpoint and multi-format support
f25a1eb test(backend): unit-test multi-format loader dispatch
caf63e1 test(backend): unit-test upload filename-collision helper
6287d00 feat(frontend): support drag-and-drop file selection in ingest panel
```

## How to run

1. **Backend:** from `Backend/` run `.\venv\Scripts\python.exe -m src.api`
   (needs Ollama running for embeddings).
2. **Frontend:** from `Frontend/` run `npm run dev`.
3. Click **Ingest** (top-right), then **Add files…** (or drag & drop), pick any
   supported file(s) from anywhere on your PC, then **Upload N files**.
