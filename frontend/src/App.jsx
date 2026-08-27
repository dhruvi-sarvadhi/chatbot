import { useEffect, useRef, useState } from 'react'
import ChatInput from './components/ChatInput.jsx'
import ConfigPanel from './components/ConfigPanel.jsx'
import DownloadMenu from './components/DownloadMenu.jsx'
import RunDetails from './components/RunDetails.jsx'
import Message from './components/Message.jsx'
import TypingDots from './components/TypingDots.jsx'
import SessionList from './components/SessionList.jsx'
import {
  deleteAllSessions,
  deleteSession,
  getConfig,
  getSession,
  likeMessage,
  listSessions,
  sendChat,
  streamChat,
  updateSession,
} from './api.js'
import { applyTheme, readTheme } from './lib/theme.js'

const SUGGESTIONS = [
  'Explain how a REST API works, simply.',
  'Give me 3 ideas for a weekend project.',
  'Write a haiku about debugging.',
]

const STORAGE_KEY = 'chatbot.config'
// Which conversation was open. Only the id lives here — the conversation
// itself is in Postgres, so any browser with this id sees the same history.
const SESSION_KEY = 'chatbot.session'

export default function App() {
  // Everything the user can change on the left. It is sent with every request,
  // so edits take effect on the very next message.
  const [config, setConfig] = useState(null)
  const [schema, setSchema] = useState(null) // providers/models/effort from the backend

  // The conversation. Entries with role "note" are local UI markers and are
  // filtered out before the history goes to the model.
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [streaming, setStreaming] = useState(true)
  const [usage, setUsage] = useState(null)
  // Every turn's metrics, so the panel can total the session.
  const [runs, setRuns] = useState([])
  const [panelOpen, setPanelOpen] = useState(false)
  const [atBottom, setAtBottom] = useState(true)
  // Text pushed into the composer by a Reply click.
  const [insert, setInsert] = useState(null)
  // Index of the message whose run details are open, or null.
  const [detailsFor, setDetailsFor] = useState(null)
  // 'system' | 'light' | 'dark' — index.html already applied the saved value.
  const [theme, setTheme] = useState(readTheme)

  // ── Stored conversations ────────────────────────────────────────────────
  // The transcript above is the live view; these are the rows in Postgres.
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_KEY))
  const [sessions, setSessions] = useState([])
  const [historyLoading, setHistoryLoading] = useState(true)
  // Set when the database is unreachable: the chat keeps working, the panel
  // says why nothing is being saved rather than showing an empty list.
  const [historyError, setHistoryError] = useState(null)
  const [panelTab, setPanelTab] = useState('chats')

  const scrollRef = useRef(null)
  const prevConfig = useRef(null)
  // Read inside effects, where the `atBottom` state value would be stale.
  const atBottomRef = useRef(true)
  // The id to send with the next turn. A ref as well as state because a turn
  // started before the server assigned an id must pick it up mid-stream,
  // where a state read would be a render behind.
  const sessionRef = useRef(sessionId)

  // Load the options + .env defaults once, then reopen the last conversation.
  // Sequenced rather than run in parallel: both set `config`, and whichever
  // resolved last would win — so a reopened chat could silently come back with
  // the wrong model.
  useEffect(() => {
    getConfig()
      .then((data) => {
        setSchema(data)
        const saved = readSaved()
        const next = saved ?? data.defaults
        setConfig(next)
        prevConfig.current = next
      })
      .catch((err) => setError(err.message))
      .finally(() => {
        const id = sessionRef.current
        if (id) openSession(id, { silent: true })
      })
  }, [])

  useEffect(() => {
    if (config) localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  }, [config])

  // Follow new output only while the user is already at the bottom — otherwise
  // reading earlier messages would be yanked away mid-stream.
  useEffect(() => {
    if (atBottomRef.current) scrollToBottom('auto')
  }, [messages, busy])

  function scrollToBottom(behavior = 'smooth') {
    const el = scrollRef.current
    el?.scrollTo({ top: el.scrollHeight, behavior })
  }

  function handleScroll(e) {
    const el = e.currentTarget
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    const bottom = distanceFromBottom < 60
    atBottomRef.current = bottom
    setAtBottom(bottom)
  }

  // Quote a message into the composer so the next question has context.
  function handleReply(text) {
    const quoted = text
      .split('\n')
      .map((line) => `> ${line}`)
      .join('\n')
    setInsert({ text: `${quoted}\n\n`, nonce: Math.random() })
  }

  function toggleLike(index) {
    const liked = !messages[index]?.liked
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, liked } : m)),
    )
    // Persist it when the message has already been written to Postgres. A
    // like on a still-streaming answer stays local until the row exists.
    const id = messages[index]?.id
    if (id) likeMessage(id, liked).catch(() => {})
  }

  // Load the sidebar. Independent of the config fetch — the list does not
  // depend on the provider catalogue, so it should not wait for it.
  useEffect(() => {
    refreshHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keep the id in the browser so a reload lands back in the same chat.
  useEffect(() => {
    if (sessionId) localStorage.setItem(SESSION_KEY, sessionId)
    else localStorage.removeItem(SESSION_KEY)
    sessionRef.current = sessionId
  }, [sessionId])

  async function refreshHistory() {
    setHistoryLoading(true)
    try {
      setSessions(await listSessions())
      setHistoryError(null)
    } catch (err) {
      // 503 from the API means Postgres is down. Say so in the panel rather
      // than showing an empty list, which would look like "no history".
      setHistoryError(err.message)
    } finally {
      setHistoryLoading(false)
    }
  }

  /** Replay a stored conversation: transcript, reasoning, metrics and config. */
  async function openSession(id, { silent = false } = {}) {
    if (busy) return
    try {
      const data = await getSession(id)
      setSessionId(data.id)
      sessionRef.current = data.id
      // Failed turns are kept in the database for debugging but are not
      // replayed: the bubble would be empty, and the transcript should show
      // the conversation, not its bookkeeping.
      const turns = data.messages.filter((m) => !m.incomplete)
      setMessages(turns.map(fromStored))
      setRuns(turns.map((m) => m.metrics).filter(Boolean))
      // Show the last turn's usage, so the strip is not blank on reopen.
      const lastRun = [...turns].reverse().find((m) => m.metrics)?.metrics
      setUsage(
        lastRun
          ? { input_tokens: lastRun.input_tokens, output_tokens: lastRun.output_tokens }
          : null,
      )
      // Restore the settings this conversation was answered with, so the next
      // turn continues it the same way rather than with whatever is in the panel.
      setConfig((prev) => {
        const next = {
          ...prev,
          provider: data.provider ?? prev?.provider,
          model: data.model ?? prev?.model,
          system_prompt: data.system_prompt ?? prev?.system_prompt,
          effort: data.effort ?? prev?.effort,
          max_tokens: data.max_tokens ?? prev?.max_tokens,
          web_search: data.web_search,
          search_backend: data.search_backend ?? prev?.search_backend,
        }
        prevConfig.current = next
        return next
      })
      setError(null)
      setPanelOpen(false)
    } catch (err) {
      // A stale id in localStorage is normal — drop it quietly on startup.
      if (silent) {
        setSessionId(null)
        return
      }
      setError(err.message)
    }
  }

  function newChat() {
    // No row is created until the first message: an empty conversation in the
    // sidebar that you never used is just clutter.
    setSessionId(null)
    sessionRef.current = null
    setMessages([])
    setUsage(null)
    setRuns([])
    setError(null)
    setPanelOpen(false)
  }

  async function renameSession(id, title) {
    // Optimistic — the row is already correct locally, so waiting on the
    // round-trip would just make the rename feel slow.
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)))
    try {
      await updateSession(id, { title })
    } catch (err) {
      setError(err.message)
      refreshHistory()
    }
  }

  async function removeSession(id) {
    try {
      await deleteSession(id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
      if (id === sessionRef.current) newChat()
    } catch (err) {
      setError(err.message)
    }
  }

  async function clearHistory() {
    if (!window.confirm('Delete every saved conversation? This cannot be undone.')) return
    try {
      await deleteAllSessions()
      setSessions([])
      newChat()
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleSend(text) {
    // If settings changed since the last reply, mark it in the transcript so
    // it is obvious which answer used which configuration.
    const changes = messages.length ? describeChanges(prevConfig.current, config) : null
    const marker = changes ? [{ role: 'note', content: changes }] : []
    prevConfig.current = config

    const history = [...messages, ...marker, { role: 'user', content: text }]
    setMessages(history)
    setBusy(true)
    setError(null)

    // "note" entries are UI-only. Empty ones are failed turns replayed from
    // the database — the API rejects a message with no content, and a turn
    // that produced nothing is not part of the conversation anyway.
    const forModel = history.filter((m) => m.role !== 'note' && m.content?.trim())

    // Timing for the reasoning panel. Kept as plain closure variables rather
    // than state: they are written from inside stream callbacks, where a state
    // value read back would be a render behind.
    let thinkStart = null
    let thinkMs = null

    try {
      if (streaming) {
        setMessages([...history, { role: 'assistant', content: '', thinking: '' }])
        await streamChat(forModel, config, sessionRef.current, {
          onTrace: (step) =>
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              next[next.length - 1] = { ...last, trace: [...(last.trace ?? []), step] }
              return next
            }),
          onStatus: (what) =>
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              next[next.length - 1] = { ...last, search: what }
              return next
            }),
          onThinking: (piece) => {
            thinkStart ??= performance.now()
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              next[next.length - 1] = {
                ...last,
                thinking: (last.thinking ?? '') + piece,
                thinkingActive: true,
              }
              return next
            })
          },
          onDelta: (delta) =>
            setMessages((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]
              // The first answer token is what ends the thinking phase.
              if (thinkStart !== null && thinkMs === null) {
                thinkMs = performance.now() - thinkStart
              }
              next[next.length - 1] = {
                ...last,
                content: last.content + delta,
                thinkingActive: false,
                thinkingMs: thinkMs ?? last.thinkingMs,
              }
              return next
            }),
          onMeta: (meta) => {
            // The server opens a conversation for us when we did not have one,
            // and tells us its id here — before a single token has arrived.
            if (meta.session_id && meta.session_id !== sessionRef.current) {
              sessionRef.current = meta.session_id
              setSessionId(meta.session_id)
            }
            setMessages((prev) => {
              const next = [...prev]
              next[next.length - 1] = { ...next[next.length - 1], meta: meta.model }
              return next
            })
          },
          onUsage: (u, metrics) => {
            setUsage(u)
            if (!metrics) return
            setRuns((prev) => [...prev, metrics])
            setMessages((prev) => {
              const next = [...prev]
              next[next.length - 1] = { ...next[next.length - 1], metrics }
              return next
            })
          },
          // Arrives after the answer is written to Postgres. Attaching the id
          // is what lets a like on this bubble be saved.
          onSaved: ({ message_id }) =>
            setMessages((prev) => {
              const next = [...prev]
              next[next.length - 1] = { ...next[next.length - 1], id: message_id }
              return next
            }),
        })
      } else {
        const data = await sendChat(forModel, config, sessionRef.current)
        if (data.session_id && data.session_id !== sessionRef.current) {
          sessionRef.current = data.session_id
          setSessionId(data.session_id)
        }
        setUsage({ input_tokens: data.input_tokens, output_tokens: data.output_tokens })
        // No timing here — a non-streamed request only reports the finished
        // reasoning, never when it started.
        setMessages([
          ...history,
          {
            id: data.message_id,
            role: 'assistant',
            content: data.reply,
            meta: data.model,
            thinking: data.thinking,
          },
        ])
      }
    } catch (err) {
      setError(err.message)
      // Remove the empty placeholder bubble if the request failed instantly.
      setMessages((prev) =>
        prev.length && prev[prev.length - 1].role === 'assistant' && !prev[prev.length - 1].content
          ? prev.slice(0, -1)
          : prev,
      )
    } finally {
      // A stream that ends during the thinking phase (an error, or a model
      // that only reasoned) would otherwise leave the panel pulsing forever.
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        if (!last?.thinkingActive) return prev
        return [
          ...prev.slice(0, -1),
          {
            ...last,
            thinkingActive: false,
            thinkingMs: thinkStart === null ? undefined : performance.now() - thinkStart,
            search: last.search === 'searching' ? 'searched:—:0' : last.search,
          },
        ]
      })
      setBusy(false)
      // Title, counts and totals all changed — pull the fresh rows.
      refreshHistory()
    }
  }

  const last = messages[messages.length - 1]
  // Once reasoning is streaming, the panel is the progress indicator — the
  // typing dots underneath it would be a second one saying the same thing.
  const waitingForFirstToken =
    busy &&
    (!last ||
      last.role === 'user' ||
      (last.role === 'assistant' && !last.content && !last.thinking && !last.search))

  return (
    <div className="layout">
      <ConfigPanel
        schema={schema}
        config={config}
        tab={panelTab}
        onTab={setPanelTab}
        history={
          <SessionList
            sessions={sessions}
            activeId={sessionId}
            loading={historyLoading}
            error={historyError}
            onSelect={openSession}
            onNew={newChat}
            onRename={renameSession}
            onDelete={removeSession}
            onClearAll={clearHistory}
            onRefresh={refreshHistory}
          />
        }
        theme={theme}
        onThemeChange={(next) => {
          setTheme(next)
          applyTheme(next)
        }}
        usage={usage}
        runs={runs}
        open={panelOpen}
        onChange={setConfig}
        onReset={() => setConfig(schema.defaults)}
        onClose={() => setPanelOpen(false)}
      />

      <div className="app">
        <header className="header">
          <div className="header__title">
            <button
              className="ghost header__gear"
              onClick={() => setPanelOpen((v) => !v)}
              aria-label="Toggle settings"
            >
              ☰
            </button>
            <span className="dot" />
            <h1>Chatbot</h1>
          </div>

          <div className="header__meta">
            {config ? (
              <span className="badge">{config.provider} · {config.model}</span>
            ) : (
              <span className="badge badge--warn">backend offline</span>
            )}

            <label className="toggle">
              <input
                type="checkbox"
                checked={streaming}
                onChange={(e) => setStreaming(e.target.checked)}
              />
              Stream
            </label>

            <label className="toggle" title="Let the model look things up when the answer needs current facts">
              <input
                type="checkbox"
                checked={Boolean(config?.web_search)}
                disabled={!config}
                onChange={(e) => setConfig({ ...config, web_search: e.target.checked })}
              />
              Web
            </label>

            <DownloadMenu
              messages={messages}
              config={config}
              disabled={!messages.length}
            />

            <button className="ghost" onClick={newChat} title="Start a new conversation">
              New chat
            </button>
          </div>
        </header>

        <main className="chat" ref={scrollRef} onScroll={handleScroll}>
          {messages.length === 0 && (
            <div className="empty">
              <h2>Start a conversation</h2>
              <p>
                Change anything on the left — provider, model, effort, tokens, system prompt —
                and the next reply uses it right away.
              </p>
              <div className="chips">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chip" onClick={() => handleSend(s)} disabled={busy || !config}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <Message
              key={i}
              role={m.role}
              content={m.content}
              meta={m.meta}
              thinking={m.thinking}
              thinkingActive={m.thinkingActive}
              thinkingMs={m.thinkingMs}
              search={m.search}
              trace={m.trace}
              metrics={m.metrics}
              pending={busy && i === messages.length - 1 && m.role === 'assistant'}
              liked={m.liked}
              onLike={() => toggleLike(i)}
              onReply={handleReply}
              onInfo={() => setDetailsFor(i)}
            />
          ))}

          {waitingForFirstToken && <TypingDots />}

          {error && <div className="error">⚠ {error}</div>}
        </main>

        <footer className="footer">
          <button
            className={`jump ${atBottom ? '' : 'jump--show'}`}
            onClick={() => scrollToBottom()}
            aria-label="Jump to latest message"
            tabIndex={atBottom ? -1 : 0}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d="M12 4v12m0 0 5-5m-5 5-5-5" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Latest
          </button>

          <ChatInput onSend={handleSend} disabled={busy || !config} insert={insert} />
          <p className="hint">Enter to send · Shift+Enter for a new line</p>
        </footer>
      </div>

      <RunDetails
        open={detailsFor != null}
        run={detailsFor != null ? messages[detailsFor]?.metrics : null}
        trace={detailsFor != null ? messages[detailsFor]?.trace : null}
        runs={runs}
        onClose={() => setDetailsFor(null)}
      />

      {panelOpen && <div className="scrim" onClick={() => setPanelOpen(false)} />}
    </div>
  )
}

/**
 * A row from Postgres, in the shape the live transcript uses.
 *
 * The two shapes differ because the live one is built from stream events:
 * `meta` is the model name, `thinkingMs` is measured in the browser. Mapping
 * here rather than renaming columns keeps the API honest about what it stores.
 */
function fromStored(m) {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    thinking: m.thinking || '',
    thinkingMs: m.thinking_ms ?? undefined,
    meta: m.model ?? undefined,
    search: m.search ?? undefined,
    trace: m.trace ?? undefined,
    metrics: m.metrics ?? undefined,
    liked: m.liked,
  }
}

function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || null
  } catch {
    return null
  }
}

/** Human-readable summary of what just changed, for the inline note. */
function describeChanges(before, after) {
  const parts = []
  if (before.provider !== after.provider) parts.push(`provider → ${after.provider}`)
  if (before.model !== after.model) parts.push(`model → ${after.model}`)
  if (before.effort !== after.effort) parts.push(`effort → ${after.effort}`)
  if (before.search_backend !== after.search_backend)
    parts.push(`search backend → ${after.search_backend}`)
  if (before.web_search !== after.web_search)
    parts.push(`web search → ${after.web_search ? 'on' : 'off'}`)
  if (before.max_tokens !== after.max_tokens) parts.push(`max tokens → ${after.max_tokens}`)
  if (before.system_prompt !== after.system_prompt) parts.push('system prompt updated')
  return parts.length ? `Settings changed: ${parts.join(' · ')}` : null
}
