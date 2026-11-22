# Voice Assistant — Neubrutalism UI Spec (React + TypeScript)

> **Audience:** an AI coding agent.
> **Task:** build the Voice Assistant screen as **React + TypeScript components** in a **neubrutalist** style (reference: Figma Community "Crude Design System – Neubrutalism").
> **Hard rule:** UI only. Do **not** modify the WebRTC / signalling / STT / LLM / TTS / backend logic. Wrap or reuse it; never rewrite it.

---

## 1. Context

The current prototype is a plain HTML page with:

- Title "Voice Assistant" + one-line subtitle
- A **Start** button and a **status pill** ("Call ended", etc.)
- A **transcript** with alternating `Assistant:` and `You:` lines
- Reply audio played back in the browser over WebRTC

Replace it with a typed React component tree. The behaviour must stay identical; only the presentation and code structure change.

### Step 0 — Inspect before writing anything

1. Detect the stack in the target folder: `package.json`, framework (Vite / Next.js / CRA), styling (Tailwind / CSS Modules / shadcn/ui), existing `tsconfig`.
2. **Follow the existing stack.** Decision rule:
   - Tailwind present → use Tailwind utilities + extend `tailwind.config` with the tokens in §3.
   - No Tailwind → use CSS Modules (`*.module.css`) with the CSS variables in §3.
   - Next.js App Router → the voice component and anything using `RTCPeerConnection`, `navigator.mediaDevices` or `window` must be a Client Component (`"use client"`).
3. Find the existing WebRTC / session code (connect, disconnect, status changes, transcript events, remote audio stream). Extract it into the hook in §5 **without changing its logic**.
4. Do not add UI libraries or animation libraries. React, TypeScript and styling only.

---

## 2. Design principles (neubrutalism)

1. Thick **black borders** (3px; 4px on the main card).
2. **Hard offset shadows**, solid black, **zero blur**.
3. **Flat, saturated colors**; no gradients, glass or soft shadows.
4. **Chunky bold uppercase** headings and buttons.
5. **Press-down** interaction on buttons (hover lifts, active pushes into the shadow).
6. Small radius (8–12px). Playful but readable: rotate only decorative stickers (≤ 1.5°).

---

## 3. Design tokens

### 3.1 If using CSS variables (`src/styles/tokens.css`, imported once globally)

```css
:root {
  --nb-bg: #FFF4E0;
  --nb-surface: #FFFFFF;
  --nb-ink: #000000;
  --nb-ink-soft: #3a3a3a;

  --nb-yellow: #FFD93D;   /* primary CTA */
  --nb-blue: #6C9CFF;     /* user bubbles */
  --nb-pink: #FF8FAB;     /* assistant bubbles */
  --nb-green: #6BDB8B;    /* live */
  --nb-red: #FF5C5C;      /* stop / error */
  --nb-lilac: #C9B6FF;    /* connecting / decorative */

  --nb-border: 3px solid var(--nb-ink);
  --nb-border-thick: 4px solid var(--nb-ink);
  --nb-shadow-sm: 3px 3px 0 var(--nb-ink);
  --nb-shadow: 6px 6px 0 var(--nb-ink);
  --nb-shadow-lg: 10px 10px 0 var(--nb-ink);
  --nb-radius-sm: 8px;
  --nb-radius: 12px;

  --nb-font-display: "Space Grotesk", system-ui, sans-serif;
  --nb-font-mono: "Space Mono", ui-monospace, monospace;
}
```

### 3.2 If using Tailwind (`tailwind.config.ts` → `theme.extend`)

```ts
import type { Config } from "tailwindcss";

export default {
  theme: {
    extend: {
      colors: {
        nb: {
          bg: "#FFF4E0",
          surface: "#FFFFFF",
          ink: "#000000",
          yellow: "#FFD93D",
          blue: "#6C9CFF",
          pink: "#FF8FAB",
          green: "#6BDB8B",
          red: "#FF5C5C",
          lilac: "#C9B6FF",
        },
      },
      boxShadow: {
        "nb-sm": "3px 3px 0 #000",
        nb: "6px 6px 0 #000",
        "nb-lg": "10px 10px 0 #000",
        "nb-hover": "8px 8px 0 #000",
      },
      borderWidth: { 3: "3px" },
      fontFamily: {
        display: ['"Space Grotesk"', "system-ui", "sans-serif"],
        mono: ['"Space Mono"', "ui-monospace", "monospace"],
      },
      keyframes: {
        pop: {
          from: { opacity: "0", transform: "translateY(8px) scale(.97)" },
          to: { opacity: "1", transform: "none" },
        },
        pulseDot: {
          "0%,100%": { transform: "scale(1)" },
          "50%": { transform: "scale(1.4)" },
        },
        bar: {
          "0%,100%": { transform: "scaleY(.2)" },
          "50%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        pop: "pop .15s ease-out",
        "pulse-dot": "pulseDot 1s ease-in-out infinite",
        bar: "bar 0.9s ease-in-out infinite",
      },
    },
  },
} satisfies Config;
```

**Fonts:** Space Grotesk (500, 700) and Space Mono (400, 700). In Next.js use `next/font/google`; in Vite add the Google Fonts `<link>` to `index.html`. Keep system fallbacks.

Page background: `--nb-bg` with a dot grid
`radial-gradient(#00000022 1.5px, transparent 1.5px)` at `22px 22px`.

---

## 4. Types

Create `src/features/voice-assistant/types.ts`. **If the existing code already defines equivalents, reuse and re-export those instead of duplicating.**

```ts
export type CallStatus = "idle" | "connecting" | "live" | "error";

export type MessageRole = "assistant" | "user";

export interface TranscriptMessage {
  id: string;            // stable key (use the existing id, or crypto.randomUUID())
  role: MessageRole;
  text: string;
}

export interface VoiceSession {
  status: CallStatus;
  statusLabel: string;               // e.g. "Call ended", "Listening…"
  messages: TranscriptMessage[];
  remoteStream: MediaStream | null;  // for <audio> playback and waveform
  start: () => Promise<void>;
  stop: () => void;
}
```

Rules: no `any`; `strict: true` must pass; export prop interfaces next to each component.

---

## 5. File / component structure

```
src/features/voice-assistant/
├─ VoiceAssistant.tsx        # page-level container (composes everything)
├─ useVoiceSession.ts        # hook: wraps EXISTING WebRTC logic -> VoiceSession
├─ types.ts
├─ components/
│  ├─ NbButton.tsx           # generic neubrutalist button
│  ├─ StatusBadge.tsx
│  ├─ CallButton.tsx         # Start / Connecting / Stop
│  ├─ Waveform.tsx
│  ├─ Transcript.tsx
│  └─ MessageBubble.tsx
└─ styles/ (only if CSS Modules)
```

### 5.1 `useVoiceSession.ts`

- Move the **existing** connect / disconnect / event-handling code here. Preserve behaviour exactly (signalling URL, ICE config, mic constraints, how transcript fragments arrive and are merged).
- Return a `VoiceSession` (see §4).
- Clean up on unmount: stop tracks, close the peer connection, remove listeners.
- Guard against double `start()` while `connecting`/`live`.
- If transcript text arrives in partial fragments, keep the current merge behaviour (update the last message of the same role rather than appending new ones, if that's what the existing code does).

### 5.2 `VoiceAssistant.tsx`

```tsx
export default function VoiceAssistant() {
  const { status, statusLabel, messages, remoteStream, start, stop } = useVoiceSession();

  return (
    <main className="min-h-screen bg-nb-bg bg-dots px-4 py-8">
      <div className="mx-auto max-w-[880px]">
        <header className="mb-8">
          <h1 className="inline-block -rotate-1 border-3 border-black bg-nb-yellow px-4 py-1 font-display text-4xl font-bold uppercase shadow-nb md:text-6xl">
            Voice Assistant
          </h1>
          <p className="mt-4 max-w-[60ch] font-medium text-neutral-700">
            Speak after pressing Start. Your browser sends microphone audio over
            WebRTC; the reply is played back here.
          </p>
        </header>

        <section className="rounded-xl border-4 border-black bg-white p-6 shadow-nb-lg">
          <div className="flex flex-col gap-4 md:flex-row md:items-center">
            <CallButton status={status} onStart={start} onStop={stop} />
            <StatusBadge status={status} label={statusLabel} />
          </div>
          <Waveform active={status === "live"} stream={remoteStream} className="mt-6" />
          <Transcript messages={messages} className="mt-6" />
        </section>

        <RemoteAudio stream={remoteStream} />
      </div>
    </main>
  );
}
```

(Equivalent CSS-Modules version is fine. The class names above are illustrative; match the repo's styling approach.)

`RemoteAudio` is a tiny component rendering a hidden `<audio autoPlay playsInline />` whose `srcObject` is set in a `useEffect` from `remoteStream`. If the existing code already attaches the stream to an audio element, keep that logic and just move it here.

### 5.3 `NbButton.tsx`

Props: `variant: "primary" | "danger" | "neutral" | "lilac"`, plus native button props (`React.ButtonHTMLAttributes<HTMLButtonElement>`).

Visual spec:
- `font-display font-bold uppercase tracking-wide`, `px-7 py-3.5`, `border-3 border-black rounded-lg shadow-nb`
- `hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-nb-hover`
- `active:translate-x-1.5 active:translate-y-1.5 active:shadow-none`
- `transition-[transform,box-shadow] duration-100`
- `focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-nb-blue`
- `disabled:` grey bg, `shadow-nb-sm`, `cursor-not-allowed`, no translate
- Min height 48px

### 5.4 `CallButton.tsx`

| `status` | Label | Variant | Disabled | Handler |
|---|---|---|---|---|
| `idle`, `error` | `▶ Start` | primary (yellow) | no | `onStart` |
| `connecting` | `Connecting…` | lilac | yes | — |
| `live` | `■ Stop` | danger (red) | no | `onStop` |

Set `aria-pressed={status === "live"}`.

### 5.5 `StatusBadge.tsx`

Hard-edged tag: `border-3 border-black rounded-lg shadow-nb-sm px-3.5 py-2 font-mono text-xs font-bold uppercase`, with a 12px round dot (`border-2 border-black`) before the label. Add `role="status"`.

| `status` | Badge bg | Dot |
|---|---|---|
| `idle` | white | grey |
| `connecting` | lilac | blinking |
| `live` | green | `animate-pulse-dot` |
| `error` | red | solid |

Show `label` (the existing human text, e.g. "Call ended") inside the badge. Color is never the only signal.

### 5.6 `Waveform.tsx`

Props: `{ active: boolean; stream?: MediaStream | null; className?: string }`.

- Container: `h-[72px] bg-nb-lilac border-3 border-black rounded-lg p-2 flex items-center gap-1`.
- 16 `<span>` bars: `flex-1 bg-black rounded-sm h-full origin-center`. Idle → `scale-y-[.2]`.
- **Default (required):** when `active`, apply the `bar` animation with staggered `animationDelay` (`${i * 60}ms`).
- **Optional upgrade:** drive heights from a Web Audio `AnalyserNode` fed by `stream` (read-only tap; never alter or reroute the existing audio). Use `requestAnimationFrame`, clean up in the effect return, and close the `AudioContext`.
- Under `prefers-reduced-motion: reduce` → no animation (`motion-reduce:animate-none`).
- Decorative: `aria-hidden="true"`.

### 5.7 `Transcript.tsx`

Props: `{ messages: TranscriptMessage[]; className?: string }`.

- Container: `role="log"`, `aria-live="polite"`, `h-[min(55vh,480px)] overflow-y-auto flex flex-col gap-4 bg-nb-bg border-3 border-black rounded-xl p-4`.
- **Auto-scroll:** keep a `ref` to a bottom sentinel; on `messages` change call `scrollIntoView({ block: "end" })` (use `behavior: "auto"` when reduced motion is preferred). Don't force-scroll if the user has scrolled up more than ~80px.
- **Empty state:** dashed black border box with centered text `PRESS START AND SAY HI 👋`.
- Custom scrollbar: 14px thumb black with a `3px` cream border, white track.
- Render `messages.map(m => <MessageBubble key={m.id} {...m} />)`.

### 5.8 `MessageBubble.tsx`

Props: `TranscriptMessage`. Wrap in `React.memo`.

- Wrapper: `flex max-w-[80%] flex-col gap-1.5 animate-pop motion-reduce:animate-none`
  - assistant → `self-start`
  - user → `self-end items-end`
- Label chip: `bg-black text-white font-mono text-[.75rem] font-bold uppercase px-2 py-0.5 rounded` → text `Assistant` / `You`.
- Bubble `<p>`: `border-3 border-black rounded-xl shadow-nb-sm px-4 py-3 font-medium leading-normal break-words`
  - assistant → `bg-nb-pink`
  - user → `bg-nb-blue`
- On screens < 768px: `max-w-[92%]`.

---

## 6. Responsiveness

- ≥ 768px: layout as in §5.2.
- < 768px: card padding `p-4`, shadows one tier smaller (`shadow-nb-lg` → `shadow-nb`), button + badge stacked, button full width, transcript height `50vh`.
- Touch targets ≥ 48px.
- Test at 375, 768 and 1280px.

## 7. Accessibility (non-negotiable)

- Black text on all palette backgrounds (never white on yellow/green/pink).
- Visible `:focus-visible` outline on every interactive element.
- Transcript = `role="log"` + `aria-live="polite"`; badge = `role="status"`.
- Call button reflects state via label text and `aria-pressed`.
- Honor `prefers-reduced-motion` (Tailwind `motion-reduce:` or a media query).
- Fully keyboard operable (Tab to the button, Enter/Space to toggle).

---

## 8. Quality bar

- TypeScript `strict` passes with **zero errors**; no `any`, no `@ts-ignore`.
- ESLint/Prettier pass using the repo's existing config.
- No unused deps added to `package.json`.
- Components are presentational (props in, JSX out); all side-effects live in `useVoiceSession` or small, cleaned-up `useEffect`s.
- No state duplication: transcript and status are owned by the hook only.
- Stable keys (`message.id`), no index keys.

## 9. Deliverables

1. Files in §5, wired into the app's existing route/page (replace the old HTML page's entry point; leave the old file in place or delete it only if clearly dead).
2. Token setup (§3) in the correct place for the repo's styling approach.
3. Font loading.
4. A short note listing every file added or changed.

## 10. Acceptance checklist

- [ ] Start connects, audio plays back, Stop ends the call — same behaviour as the HTML version
- [ ] Transcript shows both `You` and `Assistant` messages in order, auto-scrolls
- [ ] Status badge shows idle / connecting / live / error correctly
- [ ] Start button toggles Start → Connecting… → Stop and cannot be double-fired
- [ ] All borders solid black 3–4px; all shadows hard-offset with 0 blur; no gradients (except dot grid)
- [ ] Button press animation works (hover lifts, active pushes down)
- [ ] Waveform animates only while live; respects reduced motion
- [ ] Works at 375 / 768 / 1280px
- [ ] `tsc --noEmit` and lint pass; no console errors
- [ ] No WebRTC / backend logic changed (only moved into the hook)

## 11. Do NOT

- Do not rewrite or "improve" the WebRTC / STT / TTS / LLM logic.
- Do not add UI/animation libraries (no Framer Motion, MUI, Chakra, etc.).
- Do not use gradients, blurred shadows, glassmorphism or pill-shaped buttons.
- Do not rotate anything the user must read or click, except the decorative title sticker.
- Do not change the project's folder structure outside `features/voice-assistant/` and config/token files.
