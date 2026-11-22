# Setup Guide

This guide takes you from a fresh clone to a working voice assistant with a global `Ctrl + ;` hotkey. It is written for Windows because the one-command launcher and AutoHotkey integration are Windows-specific. The Python server and React UI themselves also run on macOS/Linux if you skip the hotkey steps.

> **In this PrepMate bundle:** use `..\Start-PrepMate.ps1` from the workspace root
> instead of a fresh clone. The bundled `.env` already uses port **45124** (the
> original standalone app uses 45123), points `PREPMATE_API_BASE` at the RAG
> backend on port 8000, and contains a copied Whisper model in `.cache/whisper`.
> Paste a Gemini key into `.env` for Gemini Live, or leave it blank for local
> models. Commands below that assume `D:\voice-assistant` apply here with the
> new path.

At the end you will have:

- A FastAPI server on `http://127.0.0.1:45123` that uses Gemini Live online and falls back to local models when Gemini is unreachable.
- A React UI that sends microphone audio over WebRTC and plays the reply.
- A local DuckDB database holding transcripts, memory facts, vectors, reminders and errors.
- A compact bottom-right panel toggled with `Ctrl + ;`; the backend stays warm between calls.

> [!IMPORTANT]
> Everything under `data/`, `logs/`, `.env`, the browser profile and all build output is gitignored. Never commit your API key, call history or local logs.

---

## 1. Prerequisites

| Requirement | Version / notes | Check |
| --- | --- | --- |
| Windows | 10 or 11 for the hotkey launcher | — |
| Python | 3.11 or 3.12 (3.12.6 used here) | `python --version` |
| Node.js | 20+ with npm | `node --version` |
| Gemini API key | From Google AI Studio, with the Live API enabled | — |
| Tavily API key | Backend-only key for web search tools (optional but recommended) | — |
| Ollama | Local service for embeddings and the offline chat model | `ollama --version` |
| Chrome or Edge | Installed for the launcher's app-mode window | — |
| AutoHotkey v2 | Only for the global hotkey; a portable copy is recommended | — |

Web tools need `TAVILY_API_KEY`. If you skip it, the assistant still works but cannot answer current-fact questions. `BRAVE_API_KEY` is an optional fallback. The offline fallback additionally needs the Ollama chat model plus Whisper and Piper assets (downloaded once in steps 5 and 5b).

You do **not** need a separate Pipecat installation. The repository vendors the BSD-2-Clause Pipecat source under `pipecat/src` and `bootstrap.py` puts it on `sys.path`.

---

## 2. Get the code

```powershell
git clone https://github.com/AyoAyoos/Voice-Assistant.git
cd Voice-Assistant
```

All commands below assume the project lives at `D:\voice-assistant`. If you clone somewhere else, update the two hardcoded paths in `scripts/voice-hotkey.ahk` and the Startup shortcut described in step 7.

---

## 3. Python environment

Use the folder name `.venv` exactly — the launcher looks for `.venv\Scripts\python.exe`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This installs FastAPI, aiortc, the vendored Pipecat audio stack (onnxruntime, soxr, numba, av), duckdb, httpx and loguru. The first DuckDB startup also downloads the `vss` extension if it is not cached; an internet connection is needed once. Without it, search falls back to exact cosine/keyword matching and logs a warning.

---

## 4. Configure your environment

```powershell
copy .env.example .env
notepad .env
```

Set at least:

```dotenv
GEMINI_API_KEY=your-real-key-here
```

Other defaults that usually need no change:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_LIVE_MODEL` | `gemini-3.8-live` | Live speech-to-speech endpoint |
| `GEMINI_VOICE` | `Puck` | Spoken voice |
| `GEMINI_LANGUAGE` | `en-US` | Language hint |
| `HOST` / `PORT` | `127.0.0.1` / `45123` | Bind address |
| `VOICE_DB_PATH` | `data/voice_assistant.duckdb` | Local database |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local embeddings service |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `EMBEDDING_DIM` | `768` | Must match the model and stored schema |
| `MEMORY_MODEL` | `gemini-flash-lite-latest` | Post-call fact extraction |
| `MEMORY_CONTEXT_LIMIT` / `CONTEXT_TURN_LIMIT` | `20` / `20` | Context injected per call |
| `VOICE_BACKEND` | `auto` | `auto` (Gemini with offline fallback), `gemini`, or `local` |
| `TAVILY_API_KEY` | empty | Backend-only key for `web_search` / `fetch_page` |
| `BRAVE_API_KEY` | empty | Optional search fallback when Tavily fails |
| `LOCAL_STT_MODEL` | `small.en` | faster-whisper model for offline STT |
| `LOCAL_LLM_MODEL` | `qwen2.5:3b-instruct` | Ollama chat model for offline LLM |
| `LOCAL_LLM_TEMPERATURE` | `0.7` | Local fallback LLM sampling temperature (`0`–`2`) |
| `LOCAL_TTS_VOICE` | `en_US-lessac-medium` | Piper voice for offline TTS |
| `OPENCODE_BASE_URL` | `http://127.0.0.1:28894` | Loopback-only coding service; no second agent is started |
| `OPENCODE_SERVICE_PASSWORD` | empty | Backend-only password; empty reads `~/.config/opencode/service.json` |
| `OPENCODE_PROJECT_DIR` | `D:\voice-assistant` | Live checkout used to resolve the OpenCode project id |
| `OPENCODE_WORKTREE_ROOT` | `D:\voice-assistant-worktrees` | Worktrees must be outside the project directory |
| `OPENCODE_TASK_WAIT_SECONDS` | `45` | Maximum wait inside one voice turn before saying "still running" |
| `OPENCODE_TASK_TIMEOUT_SECONDS` | `300` | Background finalizer deadline for long tasks |
| `OPENCODE_APPROVAL_TIMEOUT_SECONDS` | `60` | Unanswered approvals are rejected after this many seconds |

Notes:

- The Gemini key is sent in the `x-goog-api-key` **header**, never in a URL, and is redacted from logs and error rows. Tavily/Brave keys are likewise backend-only: never put them in React code, the browser, logs, or docs.
- If Gemini returns `404` for your memory model, keep `gemini-flash-lite-latest`. The older `gemini-2.5-flash` is no longer available to new keys.
- Other supported Live model IDs are listed in `.env.example`.
- `auto` runs a ~1 s Gemini preflight at call start; if it fails, the call uses local models and the assistant says "I'm offline, using local models." once. Set `VOICE_BACKEND=gemini` or `local` to force a mode.
- The OpenCode bridge is optional and uses the service you already run. Keep `OPENCODE_BASE_URL` on loopback only; the client rejects any other host. Leave `OPENCODE_SERVICE_PASSWORD` empty unless the backend cannot read the local service config. Never paste that password into `.env.example`, docs, logs, or chat.
- `OPENCODE_WORKTREE_ROOT` must be outside `OPENCODE_PROJECT_DIR`, so voice coding tasks never edit the live checkout. Full behavior and safety rules are in [OPENCODE_BRIDGE.md](OPENCODE_BRIDGE.md).

---

## 5. Ollama (embeddings + offline chat)

Install Ollama from <https://ollama.com>, then pull both models once:

```powershell
ollama pull nomic-embed-text          # 768-dim embeddings for memory/search
ollama pull qwen2.5:3b-instruct       # offline chat model (LOCAL_LLM_MODEL)
```

Ollama must be running when the server starts. Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

If Ollama is down, online calls still work but transcripts are stored without vectors and search uses keyword matching. Offline calls need the chat model to be present.

### 5b. Local STT and TTS assets (offline fallback)

`faster-whisper` downloads its model on first use into the Hugging Face cache; `small.en` (the default `LOCAL_STT_MODEL`) is ~500 MB. To pre-download it and avoid a delay on the first offline call:

```powershell
.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"
```

Download the Piper voice once (default `LOCAL_TTS_VOICE`):

```powershell
.\.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir "$env:USERPROFILE\.cache\piper"
```

Pass `--download-dir` explicitly: Piper's downloader otherwise writes to the current directory, while the app reads voices from `~/.cache/piper` by default. If you store voices elsewhere, set `PIPER_MODELS_DIR` in `.env`. Both assets are only needed for offline mode; Gemini Live mode does not use them.

> [!TIP]
> Both downloads contact Hugging Face. If your network resets that connection, set `$env:HF_ENDPOINT = 'https://hf-mirror.com'` in the same PowerShell session before the Whisper command. Piper's downloader hardcodes the Hugging Face host, so if it keeps failing, download `en_US-lessac-medium.onnx` and `en_US-lessac-medium.onnx.json` from `https://hf-mirror.com/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/` into `~/.cache/piper` instead.
>
> If the Whisper library still cannot download, fetch `config.json`, `tokenizer.json`, `preprocessor_config.json`, `vocabulary.txt` and `model.bin` from `https://hf-mirror.com/Systran/faster-whisper-small.en/resolve/main/` into any local folder and set `LOCAL_STT_MODEL` in `.env` to that folder's path. `WhisperModel` accepts a directory as well as a model name.

### 5c. Optional: voice-controlled OpenCode bridge

This bridge talks only to the already-running local service. It never launches another coding agent. To enable the four coding tools (`code_task`, `list_code_sessions`, `recap_code_session`, `code_permission_reply`):

1. Confirm the service is running on loopback:

   ```powershell
   opencode service status
   ```

2. Install the restricted agents. The repo copies are in `.opencode\agents\`; the running service reads the global copies:

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.config\opencode\agents" | Out-Null
   Copy-Item .opencode\agents\*.md "$env:USERPROFILE\.config\opencode\agents\"
   opencode api location.reload
   ```

   `GET /api/agent` should list `voice-coder` and `voice-planner`. The repo also ships `.opencode\opencode.jsonc` as defense-in-depth policy for manual sessions.

3. Keep the worktree root outside the checkout. The defaults in `.env.example` are `D:\voice-assistant` and `D:\voice-assistant-worktrees`; the backend refuses unsafe combinations.

4. Verify the bridge with throwaway files:

   ```powershell
   .\.venv\Scripts\python.exe scripts\verify_opencode_bridge.py
   .\.venv\Scripts\python.exe scripts\verify_opencode_approval.py
   ```

   The first script checks a read task, session listing, and recap. The second checks a spoken "yes" and the default rejection of an unanswered approval. Both may leave a worktree locked until OpenCode is restarted on Windows; see [OPENCODE_BRIDGE.md](OPENCODE_BRIDGE.md).

5. In a call, try: "Read this codebase and tell me where reminders are stored", "Plan how to add dark mode", "List my coding sessions", or "Recap session echo bravo tango". For build tasks, answer the spoken approval question with yes or no.

---

## 6. Build and run manually

Build the frontend once:

```powershell
cd D:\voice-assistant\web
npm install
npm run build
cd D:\voice-assistant
```

`npm run build` also runs `tsc --noEmit`, so it fails fast on type errors. It writes `web\dist`, which the Python server mounts. Restart the backend after the **first** build because the static directory is resolved at import time.

Start the server:

```powershell
.\.venv\Scripts\python.exe app.py
```

Verify in a browser or terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:45123/health     # {"status":"ok"}
Invoke-RestMethod http://127.0.0.1:45123/api/status # storage + embeddings info
```

Open <http://127.0.0.1:45123/>, click **Start**, allow microphone access, and say hello. Localhost is a secure browser context, so WebRTC does not need HTTPS. Headphones are recommended to prevent the assistant hearing its own output. Stop the server with `Ctrl+C`.

For frontend development with hot reload, run `npm run dev` in `web/` and open <http://127.0.0.1:5173/> while the Python server keeps running; Vite proxies `/ws` and `/api` to port 45123.

---

## 7. One-command hotkey (Windows)

### 7.1 Get AutoHotkey v2

Download the portable zip from <https://www.autohotkey.com/download/ahk-v2.zip> and place `AutoHotkey64.exe` in:

```text
D:\voice-assistant\tools\autohotkey\AutoHotkey64.exe
```

`tools/` is gitignored, so this local binary is never pushed.

### 7.2 Load the script at login

Create a shortcut in your Startup folder that runs the portable binary with the script:

```powershell
$startup = [Environment]::GetFolderPath('Startup')
$shortcut = Join-Path $startup 'Voice Assistant Hotkey.lnk'
$ws = New-Object -ComObject WScript.Shell
$link = $ws.CreateShortcut($shortcut)
$link.TargetPath = 'D:\voice-assistant\tools\autohotkey\AutoHotkey64.exe'
$link.Arguments = '"D:\voice-assistant\scripts\voice-hotkey.ahk"'
$link.WorkingDirectory = 'D:\voice-assistant'
$link.Description = 'Voice Assistant global Ctrl+; hotkey'
$link.Save()
```

Log out and back in, or run the shortcut once to start the hotkey immediately. The tray icon is labelled "Voice Assistant". After editing the `.ahk` file, use tray icon → **Reload Script**.

### 7.3 Use it

- **First `Ctrl + ;`**: opens a small always-on-top window at the bottom-right with `?compact=1&autostart=1` and starts the call automatically. The backend is already warm, so this is near-instant.
- **Second `Ctrl + ;`**: closes the panel and ends the call. **The backend stays running** so the next press is instant — use `-Stop` only for maintenance (the watchdog will restart it unless you stop the watchdog first).
- **Expand ↗** in the compact panel opens the full page with the History & Memory drawer.

The backend is kept healthy by a watchdog that starts at login; a login-time warm browser profile, memory context, embeddings, DNS/TLS, smart-turn model, and frontend build cache remove first-call delay. The launcher uses a dedicated `.voice-browser-profile` with autoplay and mic flags so the call can start without a manual click. Check `.voice-hotkey.log` for timed phase logs of every build/start/stop decision.

You can also drive it directly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\voice-assistant\scripts\voice.ps1 -Toggle
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\voice-assistant\scripts\voice.ps1 -Start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\voice-assistant\scripts\voice.ps1 -Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\voice-assistant\scripts\voice.ps1 -Status
```

---

## 8. First-run checklist

1. `GET /health` returns `{"status":"ok"}`.
2. `GET /api/status` shows `storage.available: true` and your embedding model.
3. The full page shows **Idle**, then **Listening…** → **Thinking…** → **Speaking…** during a turn.
4. After ending a call, **History & Memory** lists a session with turns.
5. `data\voice_assistant.duckdb` exists and `logs\errors.log` has no new ERROR entries.
6. `Ctrl + ;` toggles the compact panel and the backend without manual clicks.
7. Optional: `opencode service status` points at `127.0.0.1:28894`, and the bridge verification scripts pass. A coding task returns a short code such as `ecvEFlrT`.

If something fails, follow [TROUBLESHOOTING.md](TROUBLESHOOTING.md). For details on the data written, see [STORAGE_AND_MEMORY.md](STORAGE_AND_MEMORY.md). For coding sessions, approvals, models, and cleanup, see [OPENCODE_BRIDGE.md](OPENCODE_BRIDGE.md).

---

## 9. Day-to-day workflow

- Toggle the panel with `Ctrl + ;` (or `-Toggle` above). The backend stays warm; the UI is rebuilt only when its sources change, so frontend edits appear on the next press.
- Keep Ollama running in the background for semantic search, memory vectors, and offline chat.
- Keep the OpenCode service running if you use the coding bridge; resuming by short code reuses the stored worktree. Build tasks stay in their worktree until you review and clean them up manually.
- The full page at <http://127.0.0.1:45123/> is the place to browse history, memory facts, reminders and search results.
- To update the project: `git pull`, then stop and restart via `Ctrl + ;` (and re-run `pip install -r requirements.txt` if dependencies changed).

## 10. Local files you should never commit

```text
.env                         real API keys and optional OpenCODE_SERVICE_PASSWORD
data/voice_assistant.duckdb  call history, memory, vectors, errors, coding-session notebook
D:\voice-assistant-worktrees\  isolated coding worktrees; review before deleting
logs/errors.log              structured error log
.voice-hotkey.log            launcher log
.voice-backend*.log          backend stdout/stderr
.voice-pids.json             tracked backend PID
.voice-browser-profile/      browser state and mic permission
tools/autohotkey/            portable AutoHotkey binary
web/node_modules/  web/dist/  .venv/  venv/  __pycache__/
```

`.env.example` is the only configuration file tracked. If you accidentally expose a key, rotate it in Google AI Studio immediately and clear `logs/` and the `app_errors` table.
