import { useEffect, useRef, useState } from 'react'
import { ACCEPT, MAX_FILES, forWire, toAttachment } from '../lib/attachments.js'

const HISTORY_KEY = 'chatbot.history'
const HISTORY_LIMIT = 3 // how many past prompts to keep

export default function ChatInput({ onSend, disabled, insert }) {
  const [text, setText] = useState('')
  // Files staged for the next message. Cleared on send, like the text.
  const [files, setFiles] = useState([])
  const [fileError, setFileError] = useState(null)
  const [dragging, setDragging] = useState(false)
  const areaRef = useRef(null)
  const pickerRef = useRef(null)

  // The last few prompts, newest first, kept in localStorage so they survive
  // a reload. ↑ / ↓ walk through them like a shell history.
  const [history, setHistory] = useState(() => readHistory())
  // -1 = editing a fresh message; 0.. = showing history[index]
  const [index, setIndex] = useState(-1)
  // What the user had typed before they started browsing, so ↓ can restore it.
  const draftRef = useRef('')

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history))
  }, [history])

  // A Reply click elsewhere in the app drops quoted text into the box.
  // `insert` carries a nonce so replying twice with the same text still fires.
  useEffect(() => {
    if (!insert) return
    setText(insert.text)
    setIndex(-1)
    requestAnimationFrame(() => {
      const el = areaRef.current
      if (!el) return
      resize(el)
      el.focus()
      el.setSelectionRange(insert.text.length, insert.text.length)
    })
  }, [insert])

  function setValue(next) {
    setText(next)
    // The textarea auto-grows on input; recalculate after a programmatic set.
    requestAnimationFrame(() => {
      const el = areaRef.current
      if (!el) return
      resize(el)
      el.setSelectionRange(next.length, next.length) // caret to the end
    })
  }

  async function addFiles(list) {
    const room = MAX_FILES - files.length
    if (room <= 0) {
      setFileError(`Up to ${MAX_FILES} files per message`)
      return
    }

    const accepted = []
    const problems = []
    for (const file of Array.from(list).slice(0, room)) {
      try {
        accepted.push(await toAttachment(file))
      } catch (err) {
        // One bad file must not discard the good ones alongside it.
        problems.push(err.message)
      }
    }
    if (accepted.length) setFiles((prev) => [...prev, ...accepted])
    setFileError(problems.join(' · ') || null)
  }

  function submit(e) {
    e?.preventDefault()
    const trimmed = text.trim()
    // An attachment on its own is a valid message — "what is this?" is often
    // carried entirely by the picture.
    if ((!trimmed && !files.length) || disabled) return

    onSend(trimmed, files.map(forWire))
    if (trimmed) {
      setHistory((prev) => [trimmed, ...prev.filter((h) => h !== trimmed)].slice(0, HISTORY_LIMIT))
    }
    setIndex(-1)
    draftRef.current = ''
    setText('')
    setFiles([])
    setFileError(null)
    if (areaRef.current) areaRef.current.style.height = 'auto'
  }

  function handleKeyDown(e) {
    // Enter sends, Shift+Enter makes a new line.
    if (e.key === 'Enter' && !e.shiftKey) {
      submit(e)
      return
    }

    if (e.key === 'ArrowUp') {
      // Only take over the key when it would not be doing something useful:
      // an empty box, a caret already at the very start, or when we are
      // already walking the history. Otherwise ↑ still moves the caret.
      if (!history.length) return
      const el = e.currentTarget
      const atStart = el.selectionStart === 0 && el.selectionEnd === 0
      if (index === -1 && text !== '' && !atStart) return

      e.preventDefault()
      if (index === -1) draftRef.current = text
      const next = Math.min(index + 1, history.length - 1)
      setIndex(next)
      setValue(history[next])
      return
    }

    if (e.key === 'ArrowDown') {
      if (index === -1) return // not browsing — leave the caret alone

      e.preventDefault()
      const next = index - 1
      setIndex(next)
      setValue(next === -1 ? draftRef.current : history[next])
    }
  }

  function handlePaste(e) {
    const pasted = Array.from(e.clipboardData?.files ?? [])
    if (!pasted.length) return // ordinary text paste — leave it alone
    e.preventDefault()
    addFiles(pasted)
  }

  function handleChange(e) {
    setText(e.target.value)
    setIndex(-1) // typing means we are back on a fresh message
    resize(e.target)
  }

  return (
    <form
      className={`composer ${dragging ? 'composer--drop' : ''}`}
      onSubmit={submit}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
    >
      {files.length > 0 && (
        <ul className="attach">
          {files.map((f, i) => (
            <li key={i} className="attach__item">
              {f.preview ? (
                <img className="attach__thumb" src={f.preview} alt="" />
              ) : (
                <span className="attach__icon" aria-hidden="true">
                  {f.kind === 'document' ? 'PDF' : 'TXT'}
                </span>
              )}
              <span className="attach__name">{f.name}</span>
              <button
                type="button"
                className="attach__x"
                onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                aria-label={`Remove ${f.name}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      {fileError && <p className="attach__error">{fileError}</p>}

      <input
        ref={pickerRef}
        type="file"
        multiple
        accept={ACCEPT}
        hidden
        onChange={(e) => { addFiles(e.target.files); e.target.value = '' }}
      />
      <button
        type="button"
        className="composer__attach"
        onClick={() => pickerRef.current?.click()}
        disabled={disabled}
        aria-label="Attach image, PDF or text file"
        title="Attach an image, PDF or text file — or just drop one here"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M8 12v-2a4 4 0 0 1 8 0v6a6 6 0 0 1-12 0V8"
                fill="none" stroke="currentColor" strokeWidth="1.8"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <textarea
        ref={areaRef}
        rows={1}
        value={text}
        placeholder="Ask anything…"
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || (!text.trim() && !files.length)} aria-label="Send">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path
            d="M3.4 20.4 21 12 3.4 3.6l.1 6.5L15 12 3.5 13.9z"
            fill="currentColor"
          />
        </svg>
      </button>
    </form>
  )
}

function resize(el) {
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

function readHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY))
    return Array.isArray(saved) ? saved.slice(0, HISTORY_LIMIT) : []
  } catch {
    return []
  }
}
