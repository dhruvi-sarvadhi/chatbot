import { useState } from 'react'

// A debugging view of the agent loop: every request, every tool call, every
// result, stamped with when it happened.
//
// The point of it is the gaps. One answer looks like one operation from the
// outside; the trace shows it was three network round-trips and a nine-second
// pause where our own code was fetching web pages. That pause is invisible
// anywhere else.

const STEPS = {
  request: { tag: 'request', tone: 'call' },
  response: { tag: 'response', tone: 'call' },
  tool_call: { tag: 'tool', tone: 'tool' },
  tool_result: { tag: 'result', tone: 'result' },
  answer: { tag: 'answer', tone: 'done' },
  limit: { tag: 'stopped', tone: 'warn' },
}

const ms = (n) => (n < 1000 ? `${n}ms` : `${(n / 1000).toFixed(1)}s`)

export default function AgentTrace({ steps, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  if (!steps?.length) return null

  const total = steps[steps.length - 1].ms

  return (
    <div className="trace">
      <button
        type="button"
        className="trace__head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="trace__glyph" aria-hidden="true">⋯</span>
        <span>
          Agent trace · {steps.length} steps · {ms(total)}
        </span>
        <span className="trace__toggle">{open ? 'hide' : 'show'}</span>
      </button>

      {open && (
        <ol className="trace__list">
          {steps.map((s, i) => {
            const meta = STEPS[s.step] ?? { tag: s.step, tone: 'call' }
            // How long this step took = the gap until the next one. This is
            // where the time actually went, which the timestamps alone hide.
            const took = i < steps.length - 1 ? steps[i + 1].ms - s.ms : 0
            return (
              <li key={i} className={`trace__step trace__step--${meta.tone}`}>
                <div className="trace__at">{ms(s.ms)}</div>
                <div className="trace__body">
                  <div className="trace__line">
                    <span className="trace__tag">{meta.tag}</span>
                    <span className="trace__label">{s.label}</span>
                    {took > 250 && <span className="trace__took">took {ms(took)}</span>}
                  </div>
                  {s.detail && <pre className="trace__detail">{s.detail}</pre>}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
