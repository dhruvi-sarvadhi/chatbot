import { useLayoutEffect, useRef, useState } from 'react'

// A long question would otherwise push the answer off screen, so the bubble is
// capped and gets a Show more / Show less toggle. Short questions are left
// alone — the toggle only appears when the text actually overflows.
const MAX_HEIGHT = 120 // px, roughly five lines

export default function Clamped({ text }) {
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const ref = useRef(null)

  // Measure after layout: scrollHeight is the full text height even while the
  // element is capped, so this stays correct in both states.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    const measure = () => setOverflows(el.scrollHeight > MAX_HEIGHT + 8)
    measure()

    // Re-check when the bubble is resized by the window or the config panel.
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [text])

  const clamped = overflows && !expanded

  return (
    <>
      <div
        ref={ref}
        className={`clamp ${clamped ? 'clamp--on' : ''}`}
        style={clamped ? { maxHeight: MAX_HEIGHT } : undefined}
      >
        {text}
      </div>

      {overflows && (
        <button
          type="button"
          className="clamp__toggle"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </>
  )
}
