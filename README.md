# Chatbot — Python (FastAPI) + React

A minimal, working chatbot built to show **how an LLM API call actually flows**
from a browser to a Python backend to Claude / OpenAI and back.

```
┌──────────────┐   POST /api/chat        ┌──────────────┐
│ React (5173) │  { messages, config } ──►│ FastAPI      │──HTTPS──► Claude
│              │                          │   (8000)     │           or OpenAI
│ config panel │◄── reply / SSE chunks ───│  holds key   │◄──────────┘
└──────────────┘                          └──────────────┘
```

Every request carries the config panel's current settings, so changing the
provider, model, effort, token limit, or system prompt takes effect on the
**next message** — no restart, no reload.

The API key lives **only** in `backend/.env`. The browser never sees it — that is
the main reason this project has a backend at all.

---

## 1. Backend setup

```bash
cd backend
cp .env.example .env          # then open .env and paste your real API key
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Or just run `./backend/run.sh`, which does all of the above.

API is now at http://127.0.0.1:8000 — open http://127.0.0.1:8000/docs to try the
endpoints without the UI.

### Choosing the provider

In `backend/.env`:

```ini
LLM_PROVIDER=claude           # or: openai
ANTHROPIC_API_KEY=sk-ant-...  # https://console.anthropic.com/settings/keys
ANTHROPIC_MODEL=claude-opus-5
# OPENAI_API_KEY=sk-...       # https://platform.openai.com/api-keys
# OPENAI_MODEL=gpt-4o-mini
```

Change `LLM_PROVIDER`, restart the server, and the same UI now talks to the
other provider. No frontend change is needed.

## 2. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

Vite proxies every `/api/*` request to `http://127.0.0.1:8000`, so both servers
behave like one origin during development.

---

## API endpoints

| Method | Path               | What it does                                                |
|--------|--------------------|-------------------------------------------------------------|
| GET    | `/api/config`      | Providers, models, effort levels + the `.env` defaults       |
| POST   | `/api/chat`        | Send conversation → get the full reply as JSON               |
| POST   | `/api/chat/stream` | Same, but streams the reply word-by-word (SSE)               |

`/api/config` also asks each provider which models your key can actually reach,
so the panel greys out anything unavailable (cached after the first call).

Request body for both chat endpoints — `config` is optional, and anything you
leave out falls back to `backend/.env`:

```json
{
  "messages": [
    { "role": "user", "content": "Hello!" },
    { "role": "assistant", "content": "Hi — how can I help?" },
    { "role": "user", "content": "Explain REST APIs." }
  ],
  "config": {
    "provider": "openai",
    "model": "gpt-4o",
    "system_prompt": "You are a pirate.",
    "max_tokens": 2048,
    "effort": "low"
  }
}
```

The streaming endpoint emits three kinds of SSE event:

```
data: {"meta": {"provider": "openai", "model": "gpt-4o"}}
data: {"delta": "Arr"}
data: {"usage": {"input_tokens": 68, "output_tokens": 18}}
data: [DONE]
```

Try it from the terminal:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Say hi in 5 words"}]}'
```

---

## Where to look in the code

| File | Why it matters |
|------|----------------|
| [backend/app/config.py](backend/app/config.py) | Reads `.env` into a typed settings object |
| [backend/app/catalog.py](backend/app/catalog.py) | The model / effort options the panel offers |
| [frontend/src/components/ConfigPanel.jsx](frontend/src/components/ConfigPanel.jsx) | The left-hand settings panel |
| [frontend/src/components/Markdown.jsx](frontend/src/components/Markdown.jsx) | Turns a model reply into formatted output |
| [frontend/src/lib/highlight.js](frontend/src/lib/highlight.js) | Syntax highlighting, trimmed to 10 languages |
| [frontend/src/components/MessageActions.jsx](frontend/src/components/MessageActions.jsx) | Copy / reply / like / share row |
| [frontend/src/components/Clamped.jsx](frontend/src/components/Clamped.jsx) | Show more / show less for long questions |
| [frontend/src/lib/transcript.js](frontend/src/lib/transcript.js) | Markdown + JSON conversation export |
| [backend/app/providers/claude.py](backend/app/providers/claude.py) | The actual Anthropic API call |
| [backend/app/providers/openai_provider.py](backend/app/providers/openai_provider.py) | The actual OpenAI API call |
| [backend/app/main.py](backend/app/main.py) | HTTP routes, CORS, SSE streaming |
| [frontend/src/api.js](frontend/src/api.js) | `fetch` calls, including SSE parsing |
| [frontend/src/App.jsx](frontend/src/App.jsx) | Conversation state and the chat flow |

---

## Three ideas worth understanding

1. **The model has no memory.** Every request sends the entire `messages` array.
   That array *is* the conversation; drop it and the bot forgets everything.
2. **System prompt placement differs per provider.** Claude takes `system=` as a
   top-level parameter; OpenAI takes it as the first message in the list. The
   provider classes hide that difference behind one interface.
3. **`.env` sets the defaults, the panel overrides them per request.** The
   server never mutates `.env` — it merges whatever the UI sends over the
   defaults, which is why two browser tabs can use different models at once.
4. **Streaming is just a long response.** The server writes small `data: {...}`
   lines as the model generates, and the browser reads them with
   `response.body.getReader()` instead of waiting for `.json()`.

---

## The configuration panel

Everything on the left is sent with the next message:

| Control | What it changes |
|---------|-----------------|
| **API provider** | Which vendor is called. Greyed out when that key is missing from `.env`. |
| **Model** | Pick from the curated list, or type any model id in the box below it. |
| **Thinking effort** | Claude only — how long it reasons before answering. Disabled for OpenAI. |
| **Max output tokens** | Hard ceiling on one reply. |
| **System prompt** | The standing instruction sent ahead of every message. |
| **Appearance** | `system` follows your OS; `light` and `dark` override it. Saved in `localStorage` and applied before first paint, so there is no flash on reload. |

Settings persist in `localStorage`, each reply is labelled with the model that
produced it, and changing anything mid-conversation drops a divider into the
transcript so you can see which answer used which configuration.

Replies are rendered as **formatted markdown**, not raw API text — headings,
bold/italic, nested lists, tables, blockquotes, links, inline code, and fenced
code blocks with syntax highlighting and a copy button. A reply that is nothing
but bare JSON is detected and pretty-printed as a `json` block. Raw HTML in a
reply is never rendered, so a model answer cannot inject markup into the page.

A long question is capped at about five lines with a **Show more** / **Show
less** toggle, so one wall of text can't push the answer off screen. Short
questions are untouched — the toggle only appears when the text really
overflows.

Hovering a message reveals its actions — **copy** and **reply** on both
questions and answers, plus **like** and **share** on answers. Reply quotes the
message into the composer so the next question carries context; share uses the
native share sheet where the browser has one and falls back to the clipboard.
The header's **download** button saves the whole conversation as Markdown
(readable, with the reasoning folded into `<details>`) or JSON (the same shape
the API is sent, handy for replaying a run).

The composer keeps your **last 3 prompts** in `localStorage`: press ↑ / ↓ in an
empty input (or with the caret at the very start) to walk back through them,
like a shell history. ↓ past the newest restores whatever you were typing.

The transcript follows new output only while you are already at the bottom.
Scroll up and it stays put — a **↓ Latest** button fades in above the input to
take you back down.
