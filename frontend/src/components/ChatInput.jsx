import { useEffect, useRef, useState } from 'react'

const HISTORY_KEY = 'chatbot.history'
const HISTORY_LIMIT = 3 // how many past prompts to keep

export default function ChatInput({ onSend, disabled, insert }) {
  const [text, setText] = useState('')
  const areaRef = useRef(null)

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

  function submit(e) {
    e?.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || disabled) return

    onSend(trimmed)
    setHistory((prev) => [trimmed, ...prev.filter((h) => h !== trimmed)].slice(0, HISTORY_LIMIT))
    setIndex(-1)
    draftRef.current = ''
    setText('')
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

  function handleChange(e) {
    setText(e.target.value)
    setIndex(-1) // typing means we are back on a fresh message
    resize(e.target)
  }

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={areaRef}
        rows={1}
        value={text}
        placeholder="Ask anything…"
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || !text.trim()} aria-label="Send">
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
