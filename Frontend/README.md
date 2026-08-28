# Syllabus Smarts

One-Shot Lovable Prompt

Build a frontend for an existing RAG Q&A chatbot called Ask-the-Syllabus Bot, inside a frontend/ folder only — do not touch or restructure anything outside it (the Python backend already exists separately).

USING Neubrutalism theme design

Context: This is a chatbot that answers questions about course/syllabus PDFs. Users type a question, the backend retrieves relevant slide chunks, generates a grounded answer, and returns:

answer (string)

grounded (boolean — whether the answer is trustworthy/backed by sources)

citations (array of {source_file, page, distance_score})

note (string — explanation, e.g. why it refused)

There are three distinct response states the UI must visually distinguish:

Grounded answer — normal answer + citation chips (file + page)

Refused (no relevant material found) — clear "not found" message, no citations

Refused (considered but insufficient) — the model looked at sources but couldn't answer; show those sources labeled "Considered but insufficient" (visually distinct from real citations — e.g. muted/dashed style)

Pages/sections needed:

A chat interface (message list + input box) as the main view

Each bot message shows: the answer text, a grounded/refused badge, and an expandable citations panel with distance scores

A sidebar or header showing which documents are currently in the vector store (mock this with static data for now — I'll wire the real API later)

An "Ingest" panel/modal — lets a user see uploaded PDFs and simulate adding new ones (append vs. clear behavior), matching the backend's append-by-default / clear-to-reset design

Clean, modern, slightly academic aesthetic (this is a course-assessment tool, not a consumer app) — dark mode support

Technical requirements:

React + TypeScript + Tailwind

All API calls should hit placeholder functions (e.g. askQuestion(), getStoredDocuments(), ingestSource()) that I can later point at my real FastAPI/Flask backend — mock their responses realistically for now

Fully responsive

Keep everything inside frontend/, structured as its own standalone app (own package.json, not mixed with the Python project)

Suggested ReactBits components (reactbits.dev)

Match these to the specific UI moments in your app rather than sprinkling them everywhere — this is an assessment demo, so restraint reads better than a component showcase:

Where Component Why Bot's answer text appearing Text Type (or Decrypted Text) Mimics a "streaming" reveal for the grounded answer — makes the demo feel alive without needing real token streaming from Ollama Page background Aurora or Beams (subtle, low-opacity) Adds depth without distracting from a text-heavy chat UI — keep it faint Citation cards Spotlight Card or Tilted Card Good for showing source file + page + distance score as a small hoverable card, especially for the "considered but insufficient" set Document list (sidebar) Animated List Natural fit for showing ingested PDFs, with smooth add/remove when you demo the append/clear flow live "Grounded" vs "Refused" badge Shiny Text or Gradient Text for grounded; plain/muted text for refused Visual hierarchy without extra components — reserve the flashier text effect for the success state Send/ask button Glare Hover or Magnet button style Small tactile touch on the primary action Loading state (waiting on Ollama) Orbit or a simple Ribbons loader Communicates "thinking" during generation latency without feeling like a generic spinner

Skip anything from the Backgrounds category beyond one subtle choice, and avoid stacking multiple animation-heavy components in the same view — for a jury demo, the RAG mechanics (citations, grounding, refusal) should visually lead, not the UI flair.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/71f2fb0b-b256-4c32-8775-f47c84c90cfa).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
