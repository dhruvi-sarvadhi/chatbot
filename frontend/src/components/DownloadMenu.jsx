import { useEffect, useRef, useState } from 'react'
import { download, stampName, toJson, toMarkdown } from '../lib/transcript.js'

/** Header button that saves the conversation as Markdown or JSON. */
export default function DownloadMenu({ messages, config, disabled }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  // Close on an outside click or Escape, like any menu should.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function save(kind) {
    const stamp = new Date()
    const name = stampName(stamp)
    if (kind === 'md') {
      download(`${name}.md`, toMarkdown(messages, config, stamp), 'text/markdown')
    } else {
      download(`${name}.json`, toJson(messages, config, stamp), 'application/json')
    }
    setOpen(false)
  }

  return (
    <div className="dl" ref={rootRef}>
      <button
        className="ghost dl__btn"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title={disabled ? 'Nothing to download yet' : 'Download conversation'}
        aria-label="Download conversation"
        aria-expanded={open}
      >
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
          <path
            d="M12 3.5v11m0 0 4.2-4.2M12 14.5l-4.2-4.2M4.5 17v2a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-2"
            fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round"
          />
        </svg>
      </button>

      {open && (
        <div className="dl__menu" role="menu">
          <button role="menuitem" onClick={() => save('md')}>
            Markdown <span>.md</span>
          </button>
          <button role="menuitem" onClick={() => save('json')}>
            JSON <span>.json</span>
          </button>
        </div>
      )}
    </div>
  )
}
