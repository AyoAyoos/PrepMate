# Troubleshooting

Start with the four local log files:

```text
logs/errors.log                 structured backend ERROR records
.voice-hotkey.log               launcher and hotkey lifecycle
.voice-backend.log              backend stdout
.voice-backend.err.log          backend stderr and tracebacks
```

The hotkey launcher writes a timestamp line for every build, start, stop, and
failure. If nothing happens on `Ctrl + ;`, check those logs first.

## Hotkey opens the panel but does not start the call

The launcher opens `?compact=1&autostart=1`, and the React app calls `start()`
once after mount. Verify:

1. `scripts/voice.ps1` still includes `autostart=1` in `$url`.
2. The browser was launched with `--autoplay-policy=no-user-gesture-required`
   and `--use-fake-ui-for-media-stream`.
3. `.voice-backend.err.log` does not show a microphone or signaling error.
4. `logs/errors.log` does not contain a recent `/api/client-error` report.

If the panel was opened manually from `http://127.0.0.1:45123/`, press **Start**
normally; autostart is intentionally tied to the hotkey launcher URL.

## Microphone permission is denied

The browser uses a dedicated profile at `.voice-browser-profile` and passes
`--use-fake-ui-for-media-stream` to auto-approve the local mic prompt. If the
permission was previously denied in that profile:

1. Press `Ctrl + ;` to stop.
2. Delete `.voice-browser-profile`.
3. Press `Ctrl + ;` again.

A real microphone and a browser with WebRTC support are still required.
Headphones are recommended to avoid the assistant hearing its own audio.

## UI changes are not visible

The launcher runs `npm run build` on every start, so the next `Ctrl + ;` press
picks up frontend changes. If a full-page tab was already open, refresh it.
If the backend was started manually with `python app.py`, restart it after the
first build because the static directory is resolved at import time.

## Port 45123 is already in use

Check with:

```powershell
Get-NetTCPConnection -LocalPort 45123 -State Listen
```

Then either press `Ctrl + ;` to let the launcher stop its tracked backend, or
stop the other process. The launcher deliberately leaves ports it did not start
alone to avoid killing unrelated software.

The AutoHotkey script starts a watchdog (`voice.ps1 -Watch`) at login that keeps
a backend alive on this port. If you run `python app.py` manually while that
backend is healthy, the duplicate launch now prints an "already healthy"
message and exits instead of producing uvicorn's `[Errno 10048]` bind error.
The running backend is the one you want: use `Ctrl + ;` or
`http://127.0.0.1:45123/`.

To take the port over yourself:

1. Exit the AutoHotkey script from its tray icon (or stop the `voice.ps1 -Watch`
   process) so the watchdog does not restart the backend.
2. Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\voice.ps1 -Stop`.
3. Start your instance with `.\.venv\Scripts\python.exe app.py`.

To run both at once, choose another port:
`$env:PORT=45124; .\.venv\Scripts\python.exe app.py`.

## DuckDB is unavailable or the database is locked

Only one backend process should own the database file. Stop all instances, then
restart. Check `logs/errors.log` for `Could not initialize DuckDB` or
`Could not open database`. The database is at `data/voice_assistant.duckdb`
unless `VOICE_DB_PATH` is set.

To inspect it:

```powershell
.\.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect(r'data\voice_assistant.duckdb'); print(c.execute('SHOW TABLES').fetchall())"
```

## HNSW index is off

`GET /api/status` reports `hnsw: false` when DuckDB cannot load the `vss`
extension. This usually means the machine is offline and the extension is not
cached. The app still works with exact cosine fallback. To install it manually
when online:

```powershell
.\.venv\Scripts\python.exe -c "import duckdb; duckdb.connect().execute('INSTALL vss')"
```

Restart the backend afterward; indexes are rebuilt on startup.

## Ollama embeddings fail

Check the local service and model:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull nomic-embed-text
```

Then verify the endpoint:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/embed -Method Post `
  -ContentType application/json `
  -Body '{"model":"nomic-embed-text","input":["test"]}' |
  Select-Object -ExpandProperty embeddings
```

If Ollama is unavailable, `logs/errors.log` records `Ollama embedding failed`.
Calls still work, but search uses keyword matching only and no new vectors are
stored.

## Gemini setup or memory extraction fails

- Confirm `GEMINI_API_KEY` is present in `.env`.
- Confirm `GEMINI_LIVE_MODEL` is available for that key and region.
- Memory extraction uses `MEMORY_MODEL`, default `gemini-flash-lite-latest`.
  Some older models such as `gemini-2.5-flash` return `404: no longer available
  to new users`; the default avoids that.
- A failed extraction does not end the call; the local regex fallback runs.

Details are in `logs/errors.log` under `[voice-session]` or `[memory-extraction]`.

## Calls always use local models / "I'm offline, using local models."

`VOICE_BACKEND=auto` preflights Gemini each call. Check `.voice-backend.log` for the line `Voice session <id> backend: ...` — it records whether Gemini was reachable and why.

- If it says `Gemini preflight failed`, the Gemini API host is unreachable or the key is invalid/expired. Re-check `GEMINI_API_KEY` and network/DNS. With a valid key the assistant switches back to Gemini automatically on the next call.
- To force Gemini and see the real error, set `VOICE_BACKEND=gemini` and restart the backend (`Ctrl + ;` twice, then once, or use `-Stop`/`-Ensure`).
- To force local mode, set `VOICE_BACKEND=local`.

The one-time spoken notice is expected in local mode and is not an error.

## Local offline models fail to load

In local mode the first call loads Whisper and Piper. Watch `.voice-backend.err.log` for `Could not load faster-whisper` or `Could not load Piper voice`.

- Confirm the Ollama chat model exists: `ollama list` should include `qwen2.5:3b-instruct` (or your `LOCAL_LLM_MODEL`). Pull it with `ollama pull qwen2.5:3b-instruct`.
- Pre-download Whisper: `.\.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"`.
- Download the Piper voice: `.\.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir "$env:USERPROFILE\.cache\piper"`. Set `PIPER_MODELS_DIR` if voices live outside `~/.cache/piper`.
- If downloads are reset, use `https://hf-mirror.com` as described in [SETUP.md](SETUP.md); both Whisper and Piper assets live on Hugging Face. You can also download the Whisper files into a local folder and point `LOCAL_STT_MODEL` at that folder.
- If loading Whisper fails with `mkl_malloc: failed to allocate memory`, the CPU has many cores but little free RAM. The backend already defaults Whisper to 2 CPU threads; lower `LOCAL_STT_NUM_THREADS` in `.env` further (or raise it if you have spare RAM). Restart the backend after changing it.
- Confirm the packages are installed: `.\.venv\Scripts\python.exe -m pip show faster-whisper piper-tts`.

Local STT/TTS services log a warning and stay silent if their model is missing; they do not crash the call.

## Web search / fetch_page returns "unavailable"

- Confirm `TAVILY_API_KEY` is set in `.env` (backend-only). Web tools return a graceful error if it is missing.
- `BRAVE_API_KEY` is an optional fallback used only when a Tavily call fails; leave it empty to disable.
- A failed or missing key never exposes the key itself: both `pipeline.py` and `tools/voice_tools.py` redact `GEMINI_API_KEY`, `TAVILY_API_KEY`, and `BRAVE_API_KEY` before logging. Search failures appear in `logs/errors.log` as `Web search unavailable: ...` with any key replaced by `***REDACTED***`.
- The tools require outbound network access. In local/offline mode without network, audio still works but current-fact questions cannot be answered reliably.

## History is empty

Only final transcript turns after this update are stored. Memory facts require
at least one clear user statement. If Gemini extraction returns nothing, the
local fallback recognizes phrases such as "my name is", "I prefer", and
"remember that". Check:

```powershell
.\.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect(r'data\voice_assistant.duckdb'); print(c.execute('SELECT content FROM memories ORDER BY updated_at DESC LIMIT 10').fetchall())"
```

## Hotkey itself does not fire

The AutoHotkey script is `scripts/voice-hotkey.ahk` and the startup shortcut is
in the Windows Startup folder. Use the tray icon → **Reload Script** after
editing it. Verify the script directly:

```powershell
& 'D:\voice-assistant\tools\autohotkey\AutoHotkey64.exe' 'D:\voice-assistant\scripts\voice-hotkey.ahk'
```

Synthetic keyboard events from automation tools may not trigger global hotkeys;
test by physically pressing `Ctrl + ;`.

## OpenCode coding tools are unavailable

The bridge does not start a coding agent; it only calls the service you already run. Check in this order:

1. `opencode service status` should return `http://127.0.0.1:28894`. If it does not, start/restart the service before debugging the voice app.
2. `OPENCODE_BASE_URL` must stay on `127.0.0.1`, `localhost`, or `::1`. The client refuses any non-loopback URL.
3. Leave `OPENCODE_SERVICE_PASSWORD` empty unless the backend cannot read `~/.config/opencode/service.json`. The password is backend-only and never appears in tool results or logs; errors redact it as `***REDACTED***`.
4. `GET /api/agent` should include `voice-coder` and `voice-planner`. If not, copy the files from `.opencode\agents\` to `~/.config/opencode\agents\` and run `opencode api location.reload`.
5. `OPENCODE_WORKTREE_ROOT` must be outside `OPENCODE_PROJECT_DIR`. The default root is `D:\voice-assistant-worktrees`, not the live checkout.
6. Look for `tools.opencode_client` and `tools.voice_tools` warnings in `logs/errors.log` and `.voice-backend.err.log`.

If a requested model is missing, the assistant says so and retains the session's previous model. All models are allowed; there is no provider deny list. Check the live catalog with `GET /api/model` if a name looks wrong.

## OpenCode task says "still running"

`code_task` waits `OPENCODE_TASK_WAIT_SECONDS` (default 45) inside one voice turn, then returns `status: running` and a background finalizer keeps waiting up to `OPENCODE_TASK_TIMEOUT_SECONDS` (default 300). Say "Recap session <short code>" later. The row in `opencode_sessions` is updated when the task finishes. A short code is the last eight characters of the `ses_...` id.

## Approval question never arrives or times out

- In `build` mode, ask for a file edit so OpenCode requests permission. `read` and `plan` modes deny edits by design.
- "Yes", "approve", "ok", or "once" send the OpenCode decision `once`; "no", "deny", "stop", or "cancel" send `reject`. The bridge never sends `always`.
- If no spoken answer arrives within `OPENCODE_APPROVAL_TIMEOUT_SECONDS` (default 60), the backend rejects the request and marks the row `interrupted` with reason `Approval timed out`. Check `pending_permission_id` in `opencode_sessions` and `GET /api/session/{id}/permission`.
- A reply for an expired request returns `status: expired`. Start a new task instead of reusing that request id.
- Never put approvals in an `always` rule or a broad shell allowlist; keep the narrow voice policies in `.opencode\opencode.jsonc` and the per-session ruleset.

## OpenCode worktree is locked or cleanup fails

Worktrees are deliberately kept for review. On Windows, OpenCode can hold a worktree directory as its current working directory until the session is deleted and the service restarts. A direct delete may return HTTP 400 or `WinError 32`/`145`.

1. Review any changes you still need inside the worktree.
2. Delete the OpenCode session for that short code (`DELETE /api/session/{id}`).
3. Run `opencode service restart`, then rerun cleanup:

   ```powershell
   .\.venv\Scripts\python.exe -c "import asyncio,bootstrap; from tools.opencode_client import opencode_client as c; asyncio.run(c.remove_worktree(r'D:\voice-assistant-worktrees\<name>\<name>'))"
   ```

Do not force-delete a directory that contains unreviewed changes. Empty wrapper folders are removed automatically only after the nested worktree is gone.
