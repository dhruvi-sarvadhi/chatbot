// All backend calls live here, so components never deal with fetch details.
// The API key is NEVER used in the browser — it stays in the Python backend.

const BASE = '/api'

/**
 * What the browser knows and the server does not. The timezone is free and
 * needs no permission prompt — unlike navigator.geolocation, which asks the
 * user and usually is not worth it just to say "good morning" correctly.
 */
function clientContext() {
  try {
    return {
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      locale: navigator.language,
    }
  } catch {
    return {}
  }
}

/** Providers, models, effort levels and the .env defaults for the config panel. */
export async function getConfig() {
  const res = await fetch(`${BASE}/config`)
  if (!res.ok) throw new Error('Backend is not reachable')
  return res.json()
}

/** Throw the backend's own message rather than a bare status code. */
async function unwrap(res) {
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(detailOf(data) || `Request failed (${res.status})`)
  return data
}

/** FastAPI validation errors arrive as an array of objects, not a string. */
function detailOf(data) {
  const d = data?.detail
  if (!d) return ''
  if (typeof d === 'string') return d
  return Array.isArray(d) ? d.map((e) => e.msg).join('; ') : String(d)
}

/**
 * One request, one complete answer. `config` is the panel's current settings.
 * `sessionId` says which stored conversation this turn belongs to — pass null
 * and the server opens one and returns its id.
 */
export async function sendChat(messages, config, sessionId = null) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, config, context: clientContext(), session_id: sessionId }),
  })
  return unwrap(res)
}

/**
 * Streaming answer. Reads the SSE body chunk by chunk:
 *   onThinking(text) — the model reasoned a bit more (reasoning models only,
 *                      and only when it actually reasoned for this request)
 *   onStatus(what)  — "searching" / "searched": the model is looking
 *                     something up on the web
 *   onTrace(step)   — one entry of the agent loop, for the debug panel
 *   onDelta(text)   — the model wrote a bit more
 *   onMeta({provider, model, session_id}) — which model answered, and which
 *                     stored conversation the turn was filed under
 *   onUsage({input_tokens, output_tokens}, metrics) — what the turn cost:
 *                     tokens, timing split, tool calls, estimated dollars
 *   onSaved({message_id}) — the answer is now in Postgres under this id
 *
 * Reasoning always arrives before the answer, so the first onDelta is also
 * the signal that thinking is over.
 */
export async function streamChat(
  messages,
  config,
  sessionId = null,
  { onDelta, onMeta, onUsage, onThinking, onStatus, onTrace, onSaved } = {},
) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, config, context: clientContext(), session_id: sessionId }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(detailOf(data) || `Request failed (${res.status})`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? '' // keep the last, possibly incomplete, event

    for (const line of events) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (payload === '[DONE]') return

      const event = JSON.parse(payload)
      if (event.error) throw new Error(event.error)
      if (event.trace) onTrace?.(event.trace)
      if (event.status) onStatus?.(event.status)
      if (event.thinking) onThinking?.(event.thinking)
      if (event.delta) onDelta?.(event.delta)
      if (event.meta) onMeta?.(event.meta)
      if (event.usage) onUsage?.(event.usage, event.metrics ?? null)
      if (event.saved) onSaved?.(event.saved)
    }
  }
}

// ── Stored conversations ────────────────────────────────────────────────────
// The backend keeps every conversation in PostgreSQL, so history survives a
// reload, a different browser, and a server restart.

/** Sidebar rows: title, model, counts and totals — no message bodies. */
export async function listSessions({ includeArchived = false } = {}) {
  const res = await fetch(`${BASE}/sessions?include_archived=${includeArchived}`)
  return unwrap(res)
}

/** One conversation with its full transcript, reasoning and per-turn metrics. */
export async function getSession(id) {
  return unwrap(await fetch(`${BASE}/sessions/${id}`))
}

/** Open an empty conversation up front, so "New chat" has somewhere to go. */
export async function createSession(config, title) {
  const res = await fetch(`${BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, config, context: clientContext() }),
  })
  return unwrap(res)
}

/** Rename or archive. Only the fields you pass are changed. */
export async function updateSession(id, patch) {
  const res = await fetch(`${BASE}/sessions/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  return unwrap(res)
}

export async function deleteSession(id) {
  return unwrap(await fetch(`${BASE}/sessions/${id}`, { method: 'DELETE' }))
}

export async function deleteAllSessions() {
  return unwrap(await fetch(`${BASE}/sessions`, { method: 'DELETE' }))
}

/** Persist a thumbs-up so it is still there after a reload. */
export async function likeMessage(id, liked) {
  const res = await fetch(`${BASE}/messages/${id}/like`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ liked }),
  })
  return unwrap(res)
}

/** Totals across every stored conversation, with a per-model breakdown. */
export async function getStats() {
  return unwrap(await fetch(`${BASE}/stats`))
}

/** Is the API up, and is it currently able to remember anything. */
export async function getHealth() {
  return unwrap(await fetch(`${BASE}/health`))
}
