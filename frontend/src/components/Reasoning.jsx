import { useEffect, useRef, useState } from 'react'

// The model's own working-out, shown above the answer it produced.
//
// Two states, and the switch between them is the whole point of the design:
//
//   live     — expanded, pulsing, text streaming in, timer counting up.
//              This is the only moment the reasoning is the interesting thing
//              on screen, so it gets the space.
//   finished — collapsed to a single "Thought for 4.2s" line the moment the
//              first word of the answer arrives. The answer is now the
//              interesting thing; the reasoning steps out of the way but
//              stays one click from view.
export default function Reasoning({ text, active, ms }) {
  const [open, setOpen] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const bodyRef = useRef(null)
  const startRef = useRef(null)

  // Count up while the model is still thinking, so the wait has a readout
  // instead of being a silent pause.
  useEffect(() => {
    if (!active) return
    startRef.current ??= performance.now()
    const id = setInterval(() => setElapsed(performance.now() - startRef.current), 100)
    return () => clearInterval(id)
  }, [active])

  // Get out of the way as soon as the answer starts.
  useEffect(() => {
    if (!active) setOpen(false)
  }, [active])

  // Keep the newest reasoning in view while it streams.
  useEffect(() => {
    if (open && active && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [text, open, active])

  if (!text) return null

  const seconds = (ms ?? elapsed) / 1000
  const label = active
    ? `Thinking… ${seconds.toFixed(1)}s`
    : ms != null
      ? `Thought for ${seconds.toFixed(1)}s`
      : 'Reasoning'

  return (
    <div className={`reason ${active ? 'reason--live' : ''}`}>
      <button
        type="button"
        className="reason__head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="reason__glyph" aria-hidden="true" />
        <span className="reason__label">{label}</span>
        <span className="reason__toggle">{open ? 'hide' : 'show'}</span>
      </button>

      {open && (
        <div className="reason__body" ref={bodyRef}>
          {text}
          {active && <span className="caret" />}
        </div>
      )}
    </div>
  )
}
