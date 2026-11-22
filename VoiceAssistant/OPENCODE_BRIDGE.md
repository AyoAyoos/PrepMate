# Voice-controlled OpenCode bridge

This bridge lets you drive the coding service you already run locally through the voice assistant. It **does not start a second coding agent or daemon**. The Python backend only calls the loopback OpenCode HTTP service at `http://127.0.0.1:28894` and reports short, spoken summaries back to the call.

OpenCode's own database remains the source of truth for sessions and messages. The assistant's DuckDB file holds a separate, rich local notebook (`opencode_sessions`) with speakable metadata, recaps, review state, and approval state.

## What you can say

- “Read this codebase and tell me where reminders are stored.”
- “Plan how to add a dark mode toggle.”
- “Build a fix for the startup crash in the isolated worktree.”
- “List my coding sessions.” / “Recap session echo bravo tango.” / “Continue code four alpha nine with the review comments.”
- When asked for approval: “Yes, allow that once.” or “No, reject it.”

The assistant always speaks a summary: what was asked, what changed, how many files changed, the worktree path, and a one-line recap. It never reads code, patches, or diffs aloud unless you explicitly ask for file-level detail, and even then it only names files and counts.

## Architecture

```text
Voice call (Gemini Live or local fallback)
  -> tools/voice_tools.py
       code_task / list_code_sessions / recap_code_session / code_permission_reply
  -> tools/opencode_client.py
       loopback HTTP + shared SSE event stream
  -> http://127.0.0.1:28894
       existing OpenCode service
  -> isolated git worktree under D:\voice-assistant-worktrees
  -> DuckDB table opencode_sessions (local notebook only)
```

Authentication is HTTP Basic with the `opencode` user. The password is read only on the backend from `OPENCODE_SERVICE_PASSWORD` or, when that is empty, from `~/.config/opencode/service.json`. It is never sent to the browser, included in a tool result, logged, or written to documentation. Bearer-token and custom-header auth are not used.

Only loopback base URLs are accepted. If `OPENCODE_BASE_URL` points to a non-loopback host, the client refuses to start.

## Prerequisites

1. The OpenCode service is already running:

   ```powershell
   opencode service status
   # http://127.0.0.1:28894
   ```

2. The backend can authenticate. Prefer leaving `OPENCODE_SERVICE_PASSWORD` empty and letting the backend read the local service config. If you set the variable, keep it only in `.env` (gitignored, backend-only).

3. The restricted agents are installed. Repo copies live at `.opencode/agents/voice-planner.md` and `.opencode/agents/voice-coder.md`; global copies must exist at `~/.config/opencode/agents/`. After changing them, reload OpenCode:

   ```powershell
   opencode api location.reload
   # equivalent backend call: POST /api/location/reload
   ```

   `GET /api/agent` should list `voice-coder` and `voice-planner`.

4. The worktree root is **outside** the live checkout. Default:

   ```dotenv
   OPENCODE_PROJECT_DIR=D:\voice-assistant
   OPENCODE_WORKTREE_ROOT=D:\voice-assistant-worktrees
   ```

   The client refuses to create worktrees if the root is the project directory or inside it.

## Tools and return values

| Tool | Purpose | Important arguments | Speakable result |
| --- | --- | --- | --- |
| `code_task` | Start or resume a coding task | `text`, `mode` (`read`/`plan`/`build`), optional `session`, `model`, `title` | `status`, `short_code`, `session_id`, `summary`, `recap`, `file_count`, `worktree`, `review_state` |
| `list_code_sessions` | Find sessions by status or words | `limit`, `status`, `search` | Short code, title, status, mode, one-line recap, worktree |
| `recap_code_session` | Refresh and summarise one session | `session`, `include_details` | Last request, status, summary, file names/counts, milestones, review state, pending approval flag |
| `code_permission_reply` | Answer a spoken approval prompt | `decision` (`yes`/`no`, also `once`/`reject`), optional `session`, `request_id` | `awaiting_approval`, `completed`, `running`, `rejected`, `expired`, or `no_pending` |

If `code_task` returns `status: running`, the task is still active. Ask for a recap later; a background finalizer keeps waiting and writes the final summary into DuckDB.

## Modes, agents, and approvals

| Mode | Agent preferred | File edits | Shell |
| --- | --- | --- | --- |
| `read` | `voice-planner` → `plan` | Denied | Read-only git/compile/test allowlist only |
| `plan` | `voice-planner` → `plan` | Denied | Read-only git/compile/test allowlist only |
| `build` | `voice-coder` → `build` | `ask` → spoken approval | Narrow allowlist, everything else `ask` → spoken approval |

Every voice session gets an ordered permission ruleset attached directly to the OpenCode session, because voice work happens in a separate worktree outside the project root. The repo's `.opencode/opencode.jsonc` policy is defense in depth for manual sessions and never grants anything by itself.

Narrow shell allows include `git status`, `git diff`, `git log`, `git branch --show-current`, `python -m compileall`, `python -m pytest`, `npm test`, and `npm run build`. Everything else asks.

Hard denies (last matching rule wins) include:

- reading or editing `.env` and environment-like secret files (`.env.example` is documentation and remains editable)
- `external_directory`, `webfetch`, `websearch`, `subagent`, `skill`, `question`, `execute`, and MCP tool actions
- destructive shell commands: `rm`, `del`, `rmdir`, `format`, `git push`, `git reset --hard`, `git clean`, `git checkout --`, `git restore`, `Remove-Item`, `Stop-Process`, `sudo`

### Approval flow

1. The coding agent requests an edit or non-allowlisted shell command.
2. `code_task` or `code_permission_reply` returns `awaiting_approval` with a short question and request id.
3. The voice assistant asks you a simple yes/no question.
4. “Yes”, “approve”, “ok”, or “once” maps to OpenCode decision `once`. “No”, “deny”, “stop”, or “cancel” maps to `reject`.
5. If you do not answer within `OPENCODE_APPROVAL_TIMEOUT_SECONDS` (default 60), a backend timer replies `reject` automatically. The local row is marked `interrupted` with reason `Approval timed out`.

The bridge never enables `always` through the spoken tool, so one approval never becomes a standing permission.

## Models

All OpenCode models remain available. There is no provider or model deny policy. Pass a model as `provider/id`, `provider/model`, or a bare id/variant; for example:

- `ollama/qwen2.5:3b-instruct`
- `opencode/gpt-6.2-astra`
- `openrouter/anthropic/claude-sonnet-5-5`

If a requested model is not found in the live catalog, the assistant says so and keeps the session's previous/default model. If you omit `model`, OpenCode uses the agent's default.

For `code_task` specifically, omitting `model` uses an automatic chain instead of a single default:

1. `nvidia/minimaxai/minimax-m3.1-flash` (your NVIDIA NIM key, set as `NVIDIA_API_KEY` on the OpenCode service)
2. `nvidia/nemotron-3.5-lightning-30b-a3b` (a different NVIDIA model, so tier 2 is not a repeat of tier 1)
3. `ollama/qwen2.5:3b-instruct` (local, no network and no credits)

The chain skips models that are not in the live catalog and retries failed sessions with the next model. A permission prompt is never retried. Supplying `model` explicitly overrides the chain. The spoken result names the model that handled the task. Override the tiers with `VOICE_CODE_MODEL_PRIMARY`, `VOICE_CODE_MODEL_SECONDARY`, and `VOICE_CODE_MODEL_FALLBACK` in `.env`. Setting `VOICE_CODE_MODEL_SECONDARY` to an empty value makes that tier use OpenCode's own default model instead.

All three tiers run on your NVIDIA key or your own machine, so the voice coding path never spends OpenCode/OpenRouter credits.

### How this interacts with your other OpenCode tabs

The global default in `~/.config/opencode/opencode.jsonc` is also set to `nvidia/minimaxai/minimax-m3.1-flash`, so **new** tabs you open start on NVIDIA instead of the OpenRouter-backed `big-pickle` model (that model was what produced the "requires more credits" error).

- **Tabs that are already open keep their own model.** They are not retroactively changed.
- **The voice assistant never touches your tabs.** It creates its own session in its own git worktree under `D:\voice-assistant-worktrees`, outside the live checkout, and selects the model on that session only.
- **Opening the voice assistant while you work in a tab is safe.** The two run as separate OpenCode sessions with separate working directories and separate model selections.
- To use a different model in a given tab, pick it in that tab as usual; only the *default for new tabs* changed.

## Session identity and resume

- The full id looks like `ses_...`. It is kept in `opencode_session_id` and returned as `session_id`.
- The **short code** is the last eight characters, for example `ecvEFlrT`. Prefer saying this in voice calls.
- Lookups accept a short code, full id, id prefix, or words from the title.
- Resuming always sends `resume: true` and re-sends the stored `worktree_dir`, because OpenCode sessions are location-scoped.
- A baseline snapshot of `time.updated` and pending permission ids prevents the previous outcome of a resumed session from being reported as the new task's result.

The SSE stream (`GET /api/event`) is shared by all callers. Only `permission.asked`, `permission.replied`, `session.execution.*`, and `session.idle` are dispatched to per-session queues. State polling of `/api/session/{id}` and `/api/session/{id}/permission` covers reconnects or events that precede the subscription.

## Local DuckDB notebook

`opencode_sessions` is created automatically and migrated in place. Key columns:

| Column | Meaning |
| --- | --- |
| `opencode_session_id` | OpenCode source-of-truth id (primary key) |
| `short_code` | Last eight characters; the spoken handle |
| `project_id`, `worktree_dir` | OpenCode project and the isolated worktree used by this session |
| `status`, `end_reason`, `ended_at` | `running`, `succeeded`, `failed`, `interrupted`, `awaiting_approval`, or `idle`; why it ended |
| `resume_anchor` | Id of the last user message, useful as a resume anchor |
| `mode`, `agent`, `model_provider`, `model_id` | What kind of task and which agent/model ran it |
| `voice_session_id`, `title`, `last_request` | Link to the voice call and a short description |
| `summary`, `one_line_recap` | Spoken-safe summary and first sentence |
| `files_changed`, `milestones` | JSON arrays of file names and short factual milestones; no patches |
| `review_state` | Usually `unreviewed` after a build task |
| `pending_permission_*`, `pending_expires_at` | The active approval question and its default-reject deadline |
| `tokens_input`, `tokens_output`, `cost` | Usage copied from OpenCode |
| `created_at`, `updated_at`, `metadata` | Timestamps and a small JSON marker |

Rows are refreshed by `list_code_sessions`, `recap_code_session`, and background finalizers. Deleting the DuckDB file resets the notebook but not OpenCode's sessions.

## Worktrees

Each new task creates a git worktree at:

```text
<OPENCODE_WORKTREE_ROOT>/<voice-name>/<voice-name>
```

OpenCode returns the nested path; the assistant stores that path and reuses it on resume. Worktrees are **not** auto-deleted, because you may want to review, diff, or merge the changes. The live checkout is never edited by voice coding tasks.

### Why a worktree contains the whole project

A git worktree is a complete, independent checkout of the repository at the current commit. That is why a folder such as `voice-20261121-074022-9207` contains `README.md`, `app.py`, `pipecat/`, `web/`, and every other tracked file: those are the baseline files Git checks out for you, not files the voice agent created. They let the agent read the codebase and let you diff its changes in place.

Only the files reported by `git status` were created or changed by the agent. For example, a worktree with two untracked files shows:

```text
?? PROD_BACKUP_WALKTHROUGH.md
?? index.html
```

The voice tool's `file_count` and `files_changed` fields count exactly those entries, never the baseline checkout. To see only the agent's work:

```powershell
cd D:\voice-assistant-worktrees\<name>\<name>
git status --porcelain
```

To review and merge manually:

```powershell
cd D:\voice-assistant-worktrees\<name>\<name>
git status
git diff
# review, commit, cherry-pick, or merge back in the main checkout
```

To clean up a worktree after review:

```powershell
.\.venv\Scripts\python.exe -c "import asyncio,bootstrap; from tools.opencode_client import opencode_client as c; asyncio.run(c.remove_worktree(r'D:\voice-assistant-worktrees\<name>\<name>'))"
```

If Windows reports that the directory is in use, an OpenCode session is still holding it as its working directory. Delete the OpenCode session, restart the background service (`opencode service restart`), then rerun the cleanup command. Do not force-delete a directory with changes you still need.

`remove_worktree` now retries while a Windows directory lock clears, falls back to `git worktree remove --force` and `git worktree prune` when OpenCode deregisters a worktree but leaves its files behind, and removes the empty outer wrapper folder. It refuses to touch paths outside `OPENCODE_WORKTREE_ROOT`.

### Pruning old worktrees

Voice sessions accumulate over time, and each worktree is a full checkout, so old sessions can use hundreds of megabytes. This script is dry-run by default and never deletes a worktree that has untracked files or tracked edits:

```powershell
# Report what would be removed, and why
.\.venv\Scripts\python.exe scripts\prune_voice_worktrees.py

# Actually remove old clean worktrees and empty broken wrappers
.\.venv\Scripts\python.exe scripts\prune_voice_worktrees.py --apply

# More aggressive: prune clean worktrees older than one day
.\.venv\Scripts\python.exe scripts\prune_voice_worktrees.py --max-age-days 1 --apply
```

A worktree is pruned only when it is older than `--max-age-days` (default 7) **and** its git status is clean. Empty wrappers left behind by a failed earlier cleanup are always safe to remove. Worktrees containing files the agent created are always kept so you can inspect or merge them.

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENCODE_BASE_URL` | `http://127.0.0.1:28894` | Loopback-only OpenCode service |
| `OPENCODE_SERVICE_PASSWORD` | empty | Backend-only password; empty reads `~/.config/opencode/service.json` |
| `OPENCODE_PROJECT_DIR` | `D:\voice-assistant` | Live checkout used to resolve the OpenCode project id |
| `OPENCODE_WORKTREE_ROOT` | `D:\voice-assistant-worktrees` | Must be outside the project directory |
| `OPENCODE_TASK_WAIT_SECONDS` | `45` | How long a voice turn waits before saying “still running” |
| `OPENCODE_TASK_TIMEOUT_SECONDS` | `300` | Background finalizer deadline |
| `OPENCODE_APPROVAL_TIMEOUT_SECONDS` | `60` | Unanswered approvals are rejected after this many seconds |

## Verification

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py pipeline.py storage tools scripts
.\.venv\Scripts\python.exe scripts\verify_opencode_bridge.py
.\.venv\Scripts\python.exe scripts\verify_opencode_approval.py
```

Both scripts use throwaway DuckDB files and worktree roots under `%TEMP%`. They create real OpenCode sessions and may leave locked worktree directories until the service is restarted.

## Privacy notes

- No coding-agent rule permits reading `.env` files or anything outside the worktree.
- Web tools, subagents, skills, interactive questions, and MCP tool actions are denied for voice sessions.
- The service password and all API credentials stay backend-side and are redacted before logging.
- Tool results contain summaries, file names, counts, paths, and status — never patches, secret values, or headers.
- The OpenCode service must be loopback-only; non-loopback URLs are rejected by the client.
