# Chatbot — Python (FastAPI) + React

A minimal, working chatbot built to show **how an LLM API call actually flows**
from a browser to a Python backend to Claude / OpenAI and back.

```
┌──────────────┐   POST /api/chat        ┌──────────────┐
│ React (5173) │  { messages, config } ──►│ FastAPI      │──HTTPS──► Claude
│              │                          │   (8000)     │           or OpenAI
│ config panel │◄── reply / SSE chunks ───│  holds key   │◄──────────┘
│ chat history │                          └──────┬───────┘
└──────────────┘                                 │ conversations,
                                                 ▼ messages, per-turn cost
                                          ┌──────────────┐
                                          │  PostgreSQL  │
                                          └──────────────┘
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

### The database

Conversations are stored in **PostgreSQL**, so history survives a reload, a
different browser and a server restart. You need a running Postgres; the app
does the rest — it creates the database and its tables on first start.

```bash
# macOS
brew install postgresql@18 && brew services start postgresql@18
```

Then point `DATABASE_URL` in `backend/.env` at it:

```bash
DATABASE_URL=postgresql+psycopg://YOUR_USER@localhost:5432/chatbot
```

Check it worked:

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","database":"connected","database_name":"chatbot", ...}
```

Saving is never allowed to break answering. If Postgres is down the chat still
works — it just stops remembering, the **Chats** tab says why, and the log
carries a warning at startup. `PERSISTENCE_ENABLED=false` turns storage off
deliberately.

#### What gets stored

Three tables, because the interesting queries are different shapes:

| Table | One row is | Why separate |
|-------|-----------|--------------|
| `sessions` | a conversation | what the sidebar lists — queried without touching message text |
| `messages` | one turn, in `seq` order | the transcript, plus reasoning, the agent trace (JSONB) and the web-search badge |
| `runs` | what one answer cost | tokens, the model-vs-tool timing split, tool calls and dollars — aggregates that should not have to scan message bodies |

Turns that fail are recorded too, flagged `incomplete` with the error, so the
transcript you debug from is not missing the turn that broke.

Have a look with `psql`:

```bash
psql -d chatbot -c "SELECT title, last_message_at FROM sessions ORDER BY 2 DESC"
psql -d chatbot -c "SELECT model, sum(input_tokens), sum(output_tokens), sum(cost_usd) FROM runs GROUP BY 1"
```

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

| Method | Path                       | What it does                                           |
|--------|----------------------------|--------------------------------------------------------|
| GET    | `/api/config`              | Providers, models, effort levels + the `.env` defaults  |
| POST   | `/api/chat`                | Send conversation → get the full reply as JSON          |
| POST   | `/api/chat/stream`         | Same, but streams the reply word-by-word (SSE)          |
| GET    | `/api/sessions`            | The sidebar: every conversation with its counts and totals |
| POST   | `/api/sessions`            | Open an empty conversation                              |
| GET    | `/api/sessions/{id}`       | One conversation with its full transcript and metrics   |
| PATCH  | `/api/sessions/{id}`       | Rename or archive                                       |
| DELETE | `/api/sessions/{id}`       | Delete it, and its messages and runs                    |
| DELETE | `/api/sessions`            | Clear the whole history                                 |
| GET    | `/api/sessions/{id}/runs`  | Every turn's cost for one conversation                  |
| PATCH  | `/api/messages/{id}/like`  | Persist a thumbs-up                                     |
| GET    | `/api/stats`               | Totals across everything, broken down by model          |
| GET    | `/api/health`              | Is the API up, and is it currently remembering anything |

Both chat endpoints take an optional `session_id`. Leave it out and the server
opens a conversation for you and returns the id — in the JSON reply, or in the
stream's first `meta` event — so nothing has to be created up front.

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

The streaming endpoint emits one `data:` line per event:

```
data: {"meta": {"provider": "openai", "model": "gpt-4o", "session_id": "f48a4cdc-…"}}
data: {"delta": "Arr"}
data: {"usage": {"input_tokens": 68, "output_tokens": 18}}
data: {"saved": {"message_id": "b8ec82bb-…"}}
data: [DONE]
```

`meta` arrives before the first token, so the browser knows which conversation
the turn was filed under straight away. `saved` arrives last, once the answer
is actually in Postgres.

Try it from the terminal:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Say hi in 5 words"}]}'
```

---

## Clarix Projects integration

The model can read and write real projects and tasks in a Clarix workspace via
a long-lived API key, so you can say *"create a task called Fix login in the
Apollo project"* and it happens.

**Verify the connection before involving the model.** This is read-only unless
you ask for writes:

```bash
cd backend
.venv/bin/python clarix_smoke.py            # reads only
.venv/bin/python clarix_smoke.py --write    # ALSO creates a real project + task
```

It prints which workspace the key belongs to and, on failure, the one thing
worth checking next — the key, the encryption key, the gateway, or permissions.

Four things about the Clarix API that are not guessable:

- **There is no `/projects-api` URL prefix.** The app answers on bare paths
  (`/projects`, `/tasks`). That prefix serves the API reference only, and the
  paths published there carry a `{slug}` segment the gateway does not route —
  so a client generated from that spec 404s on every call.
- **Responses come back as plain JSON** for API keys, unlike the browser app's,
  which are AES-GCM enveloped. `CLARIX_ENCRYPTION_KEY` is therefore OPTIONAL —
  set it only when pointing at a Clarix build from before API-key responses
  were sent in the clear. Never accept that key as a matter of course: it is
  platform-wide and unrevocable, so holding a copy makes this integration a
  fleet-wide liability guarding a key that revokes in one click.
- **Nothing takes a name; everything takes a numeric id**, and there is no
  name filter on `GET /projects`. `clarix_client.find_project()` does the
  matching here — exact name, then code, then prefix, then substring, then an
  order-independent word match so `clarix-payroll` still finds `Payroll-Clarix`
  (people name a project by its words, not its punctuation). It
  returns *all* candidates when a term is ambiguous rather than guessing:
  `Support-Clarix`, `Payroll-Clarix` and `CRM-Clarix` all contain "Clarix", and
  answering confidently about the wrong project is worse than asking which.
- **Statuses are numeric ids, resolved per project.** There is no
  set-status-by-name call, and an assignee must already be on the project team
  or the write is rejected.
- **A task needs only a name.** Type, status and priority are required
  columns, but the API fills in the project's defaults when you omit them, so
  the tool sends just the name. (This client used to resolve all three itself —
  three extra HTTP calls per create, and it only ever fixed the problem for
  *this* integration. It was fixed server-side instead.)

### What the model can call

The main tool is `clarix_projects`, which takes an `action` rather than
splitting into eight near-identical tools — fewer tools means fewer wrong
picks. Any action taking a project accepts `project_name` *or* `project_id`;
the name is resolved for you.

| Action | Does |
|---|---|
| `get_project` | **The one to use for "tell me about project X"** — returns the project, its tasks *and* its team in one call |
| `list_projects` | The whole portfolio. Only for "what projects do I have" |
| `list_tasks` · `get_task` | Tasks in a project · one task |
| `create_project` · `create_task` · `update_task` | Writes |
| `list_task_statuses` | Per-project status ids — required before setting a status |
| `list_project_team` · `list_users` | Who may be assigned · the directory |

`get_project` exists because "tell me about project X" is always really "what
is in it and who is on it". Making the model chain three calls for that is how
it ends up answering a different question — asked for one project's tasks, it
would call `list_projects` and summarise all of them instead.

### Asking for details with a form, not a question

A second tool, `ask_user_form`, exists to kill this exchange:

```
user > create task in solnce
bot  > Sure — what should be the task name/title be?
user > ...
bot  > And a description?
```

Three fields is three round trips, and one of them (status) is a numeric id
the user has no way to know. So the model calls `ask_user_form` instead, and
a card renders in the transcript with real inputs — a title box, a description
box, and dropdowns **already populated with that project's statuses and that
project's team**, each carrying the numeric id as its value. The user fills it
in once and submits; the answers come back as one ordinary user message with
the ids already resolved, and the model writes them straight through to
`clarix_projects`.

The dropdowns are the point. Options are fetched server-side in
`tools/ask_form.py`, never guessed by the model, so a status the API would
reject cannot be picked. Name the project (`create task in Solnce`) and the
form arrives fully populated; leave it out (`add a task`) and the form asks
with a project picker instead of the bot asking in prose.

It degrades in one direction only: if the status or team lookup fails, the
form still renders with the fields that need no lookup. And it is streaming-
only — the non-streamed `/api/chat` path has no channel to push a card down,
so there the tool tells the model to ask in text and the old behaviour stands.

### Turning it off

**Settings → Clarix workspace** switches the tools off for the next message.
Two gates decide whether the model ever sees them, and they mean different
things: the panel switch is yours, and `CLARIX_API_KEY` is whether the server
has a key at all. The switch can only take the tools away, never conjure them
— with no key the row is disabled and says `no key`.

It defaults **on**, unlike web search, because it is already gated on a key
existing. The switch is there to hold live writes back on a turn where they
would be unwelcome, not to opt in. It is stored per conversation, so reopening
an old chat restores what that chat was answered with.

The key itself is never entered in, or sent to, the browser — `/api/config`
reports only *whether* one is set. Keys live in `backend/.env`, the same rule
this project already applies to the LLM keys.

Configuration lives in `backend/.env` (git-ignored; template in
`backend/.env.example`) — three keys: `CLARIX_API_URL`, `CLARIX_API_KEY`,
`CLARIX_ENCRYPTION_KEY`. Leave `CLARIX_API_KEY` empty and the tools are simply
never offered to the model.

> **Keys expire, and rotating one kills the old key an hour later.** A
> previously-working key that starts returning `401 INVALID_TOKEN` has usually
> been rotated, not revoked — `clarix_smoke.py` says which.

> **Provider support:** wired into the **OpenAI** provider, which already runs
> tools in this process. The Claude provider only declares Anthropic's
> *server-side* web search and has no local tool loop, so set
> `LLM_PROVIDER=openai` to use this.

---

## Resizing the panels

Both side panels have a draggable edge. The sidebar remembers its width and
whether you shut it; the run-details drawer remembers its width. Both are
per-browser, not per-conversation, so they are kept in `localStorage` rather
than in Postgres.

| Gesture | Does |
|---|---|
| Drag the edge | Resize. Capped at half the window — a sidebar that can eat the transcript is not a feature |
| Drag the sidebar nearly shut | Collapses it. Drag back out from the left edge to reopen |
| Double-click the edge | Toggle collapsed |
| The button left of the title | Same toggle, for people who never think to drag an edge |
| ← / → on the focused edge | Nudge 16px (48 with Shift); Home / End jump to the extremes; Enter collapses |

The handle's hit area is 11px wide but it only draws a 3px line, and only on
hover or focus — a 3px target is a miss most of the time, and a visible
divider at rest is noise. Below 820px the sidebar stops being a column and
becomes an overlay drawer, so there is no edge between two things to drag and
the handle hides itself.

---

## Where to look in the code

| File | Why it matters |
|------|----------------|
| [backend/app/config.py](backend/app/config.py) | Reads `.env` into a typed settings object |
| [backend/app/catalog.py](backend/app/catalog.py) | The model / effort options the panel offers |
| [backend/app/models.py](backend/app/models.py) | The three tables, and why the schema is shaped that way |
| [backend/app/store.py](backend/app/store.py) | Every database read and write, in one place |
| [backend/app/db.py](backend/app/db.py) | Engine, pooling, and creating the database on first run |
| [frontend/src/components/SessionList.jsx](frontend/src/components/SessionList.jsx) | The chat history sidebar |
| [frontend/src/components/ConfigPanel.jsx](frontend/src/components/ConfigPanel.jsx) | The left-hand settings panel |
| [frontend/src/components/Resizer.jsx](frontend/src/components/Resizer.jsx) | The draggable edge that resizes the sidebar and the details drawer |
| [frontend/src/components/Markdown.jsx](frontend/src/components/Markdown.jsx) | Turns a model reply into formatted output |
| [frontend/src/lib/highlight.js](frontend/src/lib/highlight.js) | Syntax highlighting, trimmed to 10 languages |
| [frontend/src/components/MessageActions.jsx](frontend/src/components/MessageActions.jsx) | Copy / reply / like / share row |
| [frontend/src/components/Clamped.jsx](frontend/src/components/Clamped.jsx) | Show more / show less for long questions |
| [frontend/src/components/RunDetails.jsx](frontend/src/components/RunDetails.jsx) | The per-answer analytics drawer |
| [frontend/src/lib/transcript.js](frontend/src/lib/transcript.js) | Markdown + JSON conversation export |
| [backend/app/clarix_client.py](backend/app/clarix_client.py) | Clarix HTTP client — auth, and decrypting every reply |
| [backend/app/tools/clarix_projects.py](backend/app/tools/clarix_projects.py) | The Clarix tool the model calls, and what it tells the model when a call fails |
| [backend/app/tools/ask_form.py](backend/app/tools/ask_form.py) | Builds the form the model shows instead of asking field by field |
| [frontend/src/components/ToolForm.jsx](frontend/src/components/ToolForm.jsx) | Renders that form, and turns the answers back into a message |
| [backend/clarix_smoke.py](backend/clarix_smoke.py) | Prove the Clarix key works without an LLM in the way |
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

Every answer carries a **Details** (ⓘ) action that opens a right-hand drawer
with the whole run: headline numbers, where the time went (model vs your own
tools), what you paid for (input / cached / output / reasoning), plain-language
findings, a per-model comparison across the session, and the step-by-step agent
trace. The comparison is the point — one run's numbers mean little on their own,
but against the other models you have tried they turn into a decision.

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
