# PrepMate — Ask-the-Syllabus Bot + Voice Assistant

PrepMate is a Retrieval-Augmented Generation (RAG) Q&A system over course/syllabus
PDFs. It answers **exclusively from retrieved context** with readable source
citations, and refuses rather than hallucinating when nothing relevant is found.

The bundled **Voice Assistant** adds a live, spoken front end without leaving the
chat: press the mic in the chat UI, ask a course question out loud, and the agent
looks up the answer through PrepMate's `/ask` API before replying over WebRTC
audio. Voice and typed chat share one DuckDB + HNSW course index; the voice
process never reads course files directly.

## Project layout

```
PrepMate/
├── Backend/          Python RAG backend (ingest → retrieve → generate + eval)
├── Frontend/         React + TanStack chat UI with inline WebRTC voice calls
├── VoiceAssistant/   Bundled voice agent (FastAPI + WebRTC; no UI popup)
├── Start-PrepMate.ps1  Starts/stops all services (Windows)
└── .prepmate-pids.json Runtime PID file (gitignored)
```

## Quick start (all services, one command)

From `D:\GEN_AI\PrepMate` in PowerShell:

```powershell
.\Start-PrepMate.ps1             # backend + voice + frontend
.\Start-PrepMate.ps1 -Status     # health check
.\Start-PrepMate.ps1 -Stop       # shut everything down
```

Use `-NoFrontend` if you only want the Python services. Logs are written to
`logs/<service>.out.log` and `logs/<service>.err.log`.

### One-time setup

```powershell
# 1. RAG backend
cd Backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
# Ollama must be running with the models named in Backend/.env

# 2. Voice assistant
cd ..\VoiceAssistant
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
# Optional: paste a real key after GEMINI_API_KEY= for Gemini Live.
# Leave it blank to use local Ollama + faster-whisper + Piper instead.
```

The bundled `.env` already points the voice agent at `PREPMATE_API_BASE=http://127.0.0.1:8000`
and uses port `45124`. A copied Whisper model lives in `VoiceAssistant/.cache/whisper/small.en`;
the Piper voice and Ollama models are reused from your local cache.

## How the integration works

1. **UI → Voice:** the **Voice** button (header or composer mic) expands an inline
   call strip inside the chat column. It uses WebRTC signaling directly against
   `http://127.0.0.1:45124` — no dialog, popup, or iframe. Spoken turns are added
   to the same message list as typed questions.
2. **Voice → RAG:** the agent has a `syllabus_search` tool. For course-related
   questions it POSTs to `PREPMATE_API_BASE/ask`, then speaks the grounded answer.
   The backend serves both chat and voice from `Backend/vectorstore/course.duckdb`
   with a cosine HNSW index; the voice process has no course-file access.
3. **Fallbacks:** with a Gemini key the agent uses Gemini Live. Without one it uses
   local Whisper (STT), Ollama (LLM) and Piper (TTS). Web search remains optional
   and needs `TAVILY_API_KEY`.

## Ports

| Service | Default URL |
| --- | --- |
| RAG backend | http://localhost:8000 (docs at `/docs`) |
| Voice assistant | http://127.0.0.1:45124 |
| Frontend | printed by `npm run dev` |
| Ollama | http://127.0.0.1:11434 |

## Manual start (alternative)

```powershell
# Terminal 1 — RAG backend
cd Backend; .\venv\Scripts\python.exe -m src.api

# Terminal 2 — Voice assistant
cd VoiceAssistant; .\.venv\Scripts\python.exe app.py

# Terminal 3 — Frontend
cd Frontend; npm install; npm run dev
```

## Subproject docs

- [Backend/README.md](Backend/README.md) — ingestion, retrieval, evaluation.
- [VoiceAssistant/README.md](VoiceAssistant/README.md) — voice pipeline, tools, memory.
- [VoiceAssistant/SETUP.md](VoiceAssistant/SETUP.md) — local model setup and troubleshooting.
