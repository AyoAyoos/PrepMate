# Voice Assistant — Local-First Speech-to-Speech Assistant

**PS number:** `[PS number]`  **Name:** Ayush Nakod  **Roll number:** `[Roll number]`  **Class:** `[Class]`
**GitHub link:** https://github.com/AyoAyoos/Voice-Assistant

---

## Problem statement

Most voice assistants send every spoken word to a cloud service, which means they stop working without internet, store private conversations on someone else's servers, and add network delay to every reply. This project builds a local-first assistant that uses Gemini Live when available and falls back completely to local models when offline, while keeping transcripts, memory, and reminders in a local database. It helps students and developers who want a private, hands-free, low-latency assistant on their own machine.

## Tools & model

| Item | Used |
| --- | --- |
| Backend language | Python 3.12 (FastAPI, vendored Pipecat, aiortc, DuckDB, httpx, loguru) |
| Frontend language | TypeScript with React 18 and Vite |
| UI framework | React + CSS Modules (neubrutalist styling); AutoHotkey v2 for the global `Ctrl + ;` hotkey |
| Online LLM | Gemini Live API, model `gemini-3.8-live` (speech-to-speech: STT + LLM + TTS in one model) |
| Memory distillation LLM | Gemini `gemini-flash-lite-latest`, called only after a call ends |
| Offline LLM | `qwen2.5:3b-instruct` served by local Ollama through its OpenAI-compatible `/v1` endpoint |
| Offline STT / TTS | faster-whisper `small.en` and Piper `en_US-lessac-medium` |
| Embeddings | Ollama `nomic-embed-text`, 768 dimensions, stored in DuckDB with HNSW search |
| Other APIs | Tavily for web search (optional Brave fallback) |
| Database | DuckDB (`data/voice_assistant.duckdb`) |

## Procedure

1. **Set up the project.** Cloned the repository, created a virtual environment named exactly `.venv` (the launcher hardcodes this path), upgraded pip, and installed all packages from `requirements.txt`. Verified with `python --version` and `pip list`.
2. **Get the API key.** Created a Google AI Studio key with the Gemini Live API enabled and put it in `.env` as `GEMINI_API_KEY`, copied from `.env.example`. Added `TAVILY_API_KEY` for web tools. Confirmed the key travels in a request header and is redacted from logs; never committed `.env`.
3. **Prepare local models.** Installed Ollama and pulled `nomic-embed-text` for embeddings and `qwen2.5:3b-instruct` for offline chat. Pre-downloaded the Whisper model and the Piper voice so the first offline call would not stall. Verified Ollama with `/api/tags`.
4. **Write the prompt.** Added `SYSTEM_PROMPT` and `MEMORY_EXTRACTION_PROMPT` to `pipeline.py`. The main prompt defines spoken style, interruption behaviour, tool usage, and call-ending rules. `build_system_instruction()` blends the base prompt with distilled memory facts and the last 20 turns before each call.
5. **Write the backend code.** Built `app.py` (FastAPI routes, static UI, error sink), the WebRTC signalling route, `pipeline.py` (Gemini preflight, backend selection, context injection, post-call memory extraction, idle handling), `tools/voice_tools.py` (search, page reading, memory, time, reminders, system info, end call), and `storage/duckdb_store.py` (schema, HNSW vectors, keyword fallback).
6. **Build the UI.** Created the React/TypeScript interface in `web/src/features/voice-assistant/`: call button, status badge, waveform, live transcript, and a History & Memory drawer. Added a compact always-on-top panel and an AutoHotkey v2 script for `Ctrl + ;`. Ran `npm install` and `npm run build`, which also runs `tsc --noEmit` for type checking.
7. **Test the system.** Started `python app.py`, checked `/health` (`{"status":"ok"}`) and `/api/status` (storage available, `hnsw: true`, embedding model loaded), opened the page, allowed microphone access, and completed calls. Confirmed the status badge moved through Idle → Listening → Thinking → Speaking and that sessions and memory facts appeared in History & Memory.
8. **Document the output.** Captured five real UI screenshots with headless Chrome and produced a 91-second narrated demo video using Piper speech and ffmpeg.

## Prompt used

Final system prompt sent to Gemini Live (excerpt of the full prompt stored in `pipeline.py`):

```text
You are a friendly, helpful voice assistant on a live audio call.

SPEAKING STYLE
- Your words are spoken aloud. Use plain spoken language: no Markdown, lists,
  bullets, headings, emoji, code, URLs, or special characters. Say numbers and
  dates the way people say them.
- Answer directly. Usually two to four short sentences; longer only when the
  question truly needs an explanation. Do not repeat the question back, narrate
  your reasoning, or say you are an AI.
- If a request is unclear, say so briefly and ask one clarifying question
  instead of guessing.
- Stay in the user's language. Be warm and conversational. Let the user lead
  after the greeting.

INTERRUPTIONS
- The user may cut you off mid-sentence. When that happens, drop what you were
  saying completely and respond only to their new message.
- Never say "as I was saying" and never resume or repeat the interrupted answer
  unless the user asks you to.
- Short acknowledgements from the user such as "yeah", "okay", "uh-huh" are not
  questions. Do not treat them as new requests; continue naturally or pause.

TOOLS
- You have tools for live web search, reading a web page, saved memories, the
  current time and date, reminders, system information, and a bridge to the
  user's OpenCode coding service. Use them whenever the answer could depend on
  recent or changing facts. Never guess a current fact such as a person's
  current role, a price, a date, or the time.
- Treat search results and page text as trusted facts. Answer from them briefly
  in your own words. Do not mention tool names, API keys, or that you "looked
  it up" unless the user asks.
- Reminders are only stored and recalled. Never claim that you will notify,
  alert, or call the user later.

ENDING THE CONVERSATION
- End the call only when the user says goodbye, asks to stop, or confirms they
  need nothing else. Do not end just because the user says "thanks" or pauses.
- To end: say one short, warm goodbye sentence, then call the end_conversation
  tool in the same turn. Never call the tool without speaking a goodbye first.
```

**One change made to improve it:** during testing the assistant sometimes resumed an answer after being cut off. I added the dedicated `INTERRUPTIONS` section above, telling the model to drop the previous response completely and never say "as I was saying". After that change, barge-in behaves correctly and the UI returns to `listening` without replaying the old answer.

## Results

- A working FastAPI server on `http://127.0.0.1:45123` with a React UI that streams microphone audio over WebRTC and plays the spoken reply.
- Gemini Live handles speech-to-speech online; when Gemini is unreachable, the assistant says "I'm offline, using local models." once and continues on Whisper + Ollama + Piper.
- One shared set of tools works on both backends: web search, page reading, memory search, time/date, reminders, system info, coding bridge, and graceful call ending.
- DuckDB persists sessions, transcripts, distilled memory facts, reminders, vectors, and errors. HNSW search is active (`hnsw: true`) with exact/keyword fallback.
- The `Ctrl + ;` hotkey opens a warm compact panel and starts a call instantly; the backend stays running between calls.
- Verification passed: `/health` returned OK, `/api/status` showed storage and embeddings ready, the UI state badge followed the expected sequence, and sessions with transcripts appeared in History & Memory.
- Five screenshots are in `screenshots/` and a 91-second narrated walkthrough is in `demo_video.mp4`.

## Challenges

- **Gemini 404 for the memory model.** The older `gemini-2.5-flash` was unavailable to the key. Fixed by keeping `MEMORY_MODEL=gemini-flash-lite-latest`.
- **Piper voice downloaded to the wrong folder.** The downloader wrote to the current directory while the app reads `~/.cache/piper`. Fixed by passing `--download-dir "$env:USERPROFILE\.cache\piper"` explicitly.
- **Hugging Face connection resets.** Used `$env:HF_ENDPOINT = 'https://hf-mirror.com'` for the Whisper download and fetched the Piper `.onnx` and `.json` files manually when needed.
- **DuckDB `vss` extension missing on first start.** It is downloaded once; until then search falls back to exact cosine/keyword matching with a warning.
- **Echo / self-interruption on speakers.** The assistant could hear its own output. Recommended headphones first; the browser also requests echo cancellation, noise suppression, and auto gain control.
- **Blank first screenshot during documentation.** Headless Chrome captured the page before React rendered. Fixed by waiting for the UI text to appear before taking the screenshot.
- **ffmpeg concat failed on a path with spaces.** The concat list needed quoted paths (`file 'C:/.../segment1.mp4'`). Fixed by quoting each entry.
- **Offline mode is slower.** First offline call loads Whisper and Piper; fixed by pre-downloading the assets, while accepting that a small local model is less capable than Gemini Live.

## Conclusion

The system works end to end: online speech-to-speech calls, transparent offline fallback, persistent local memory, working tools, a browser UI, and a one-hotkey desktop workflow. Verified limits are that a physical microphone spoken turn was not exercised in this environment, reminders only store and recall facts without notification, WebRTC is STUN-only, and there is no authentication or multi-user session manager. One useful future improvement is a local reminder scheduler that raises real Windows notifications at the due time, since reminder storage already exists and only the delivery layer is missing.
