import { useState } from 'react'

// The chat history, read straight from PostgreSQL. Each row is one stored
// conversation; clicking it replays the transcript, metrics and reasoning
// exactly as they were when it happened.

export default function SessionList({
  sessions,
  activeId,
  loading,
  error,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onClearAll,
  onRefresh,
}) {
  // Which row is being renamed, and the in-progress text. Kept here rather
  // than in App: nothing outside this list cares about a half-typed title.
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState('')
  // Two-step delete — the second click on the same row confirms it.
  const [confirming, setConfirming] = useState(null)

  function startRename(session) {
    setEditing(session.id)
    setDraft(session.title)
  }

  function commitRename(id) {
    const title = draft.trim()
    setEditing(null)
    if (title && title !== sessions.find((s) => s.id === id)?.title) onRename(id, title)
  }

  return (
    <div className="history">
      <div className="history__actions">
        <button className="history__new" onClick={onNew}>
          <PlusIcon />
          New chat
        </button>
        <button
          className="ghost history__refresh"
          onClick={onRefresh}
          title="Reload the list from the database"
          aria-label="Refresh history"
        >
          <RefreshIcon />
        </button>
      </div>

      {error && (
        <p className="history__empty history__empty--warn">
          {error}
        </p>
      )}

      {!error && loading && sessions.length === 0 && (
        <p className="history__empty">Loading history…</p>
      )}

      {!error && !loading && sessions.length === 0 && (
        <p className="history__empty">
          No saved conversations yet. Send a message and it will appear here.
        </p>
      )}

      <ul className="history__list">
        {sessions.map((s) => (
          <li
            key={s.id}
            className={`history__item ${s.id === activeId ? 'is-active' : ''}`}
          >
            {editing === s.id ? (
              <input
                className="history__rename"
                value={draft}
                autoFocus
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => commitRename(s.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(s.id)
                  if (e.key === 'Escape') setEditing(null)
                }}
              />
            ) : (
              <button
                className="history__open"
                onClick={() => onSelect(s.id)}
                title={s.title}
              >
                <span className="history__title">{s.title}</span>
                <span className="history__meta">
                  {when(s.last_message_at ?? s.created_at)}
                  {s.message_count > 0 && ` · ${s.message_count} msg`}
                  {s.model && ` · ${s.model}`}
                  {s.cost_usd != null && ` · $${s.cost_usd.toFixed(4)}`}
                </span>
              </button>
            )}

            <div className="history__row-actions">
              <button
                className="ghost history__icon"
                onClick={() => startRename(s)}
                title="Rename"
                aria-label={`Rename ${s.title}`}
              >
                <PencilIcon />
              </button>
              <button
                className={`ghost history__icon ${confirming === s.id ? 'is-danger' : ''}`}
                onClick={() => {
                  if (confirming === s.id) {
                    onDelete(s.id)
                    setConfirming(null)
                  } else {
                    setConfirming(s.id)
                    // Arm for a few seconds only — a stray click much later
                    // should not silently delete a conversation.
                    setTimeout(() => setConfirming((c) => (c === s.id ? null : c)), 4000)
                  }
                }}
                title={confirming === s.id ? 'Click again to delete' : 'Delete'}
                aria-label={`Delete ${s.title}`}
              >
                {confirming === s.id ? <CheckIcon /> : <TrashIcon />}
              </button>
            </div>
          </li>
        ))}
      </ul>

      {sessions.length > 0 && (
        <button className="ghost history__clear" onClick={onClearAll}>
          Delete all conversations
        </button>
      )}
    </div>
  )
}

/* ── icons: same 24-box, stroked, currentColor set as the message actions ── */
const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Icon({ children }) {
  return <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">{children}</svg>
}

function PlusIcon() {
  return <Icon><path d="M12 5v14M5 12h14" {...stroke} /></Icon>
}

function RefreshIcon() {
  return (
    <Icon>
      <path d="M20 12a8 8 0 1 1-2.4-5.7" {...stroke} />
      <path d="M20 4v4.5h-4.5" {...stroke} />
    </Icon>
  )
}

function PencilIcon() {
  return (
    <Icon>
      <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z" {...stroke} />
      <path d="M14.5 5.5l4 4" {...stroke} />
    </Icon>
  )
}

function TrashIcon() {
  return (
    <Icon>
      <path d="M4.5 6.5h15" {...stroke} />
      <path d="M9.5 6.5V5a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 5v1.5" {...stroke} />
      <path d="M6.5 6.5 7.4 19a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4l.9-12.5" {...stroke} />
      <path d="M10.5 10v6.5M13.5 10v6.5" {...stroke} />
    </Icon>
  )
}

function CheckIcon() {
  return <Icon><path d="m5 13 4.5 4.5L19 7" {...stroke} strokeWidth={2} /></Icon>
}

/** Compact relative time — a sidebar row has no space for a full date. */
function when(iso) {
  if (!iso) return 'new'
  const then = new Date(iso)
  const mins = Math.round((Date.now() - then.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`
  if (mins < 60 * 24 * 7) return `${Math.round(mins / (60 * 24))}d ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
