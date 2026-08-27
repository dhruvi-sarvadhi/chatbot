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

/** One request, one complete answer. `config` is the panel's current settings. */
export async function sendChat(messages, config) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, config, context: clientContext() }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

/**
 * Streaming answer. Reads the SSE body chunk by chunk:
 *   onThinking(text) — the model reasoned a bit more (reasoning models only,
 *                      and only when it actually reasoned for this request)
 *   onStatus(what)  — "searching" / "searched": the model is looking
 *                     something up on the web
 *   onTrace(step)   — one entry of the agent loop, for the debug panel
 *   onDelta(text)   — the model wrote a bit more
 *   onMeta({provider, model}) — which model actually answered
 *   onUsage({input_tokens, output_tokens}, metrics) — what the turn cost:
 *                     tokens, timing split, tool calls, estimated dollars
 *
 * Reasoning always arrives before the answer, so the first onDelta is also
 * the signal that thinking is over.
 */
export async function streamChat(
  messages,
  config,
  { onDelta, onMeta, onUsage, onThinking, onStatus, onTrace } = {},
) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, config, context: clientContext() }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `Request failed (${res.status})`)
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
    }
  }
}
