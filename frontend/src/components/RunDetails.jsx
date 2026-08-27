import { useEffect } from 'react'
import AgentTrace from './AgentTrace.jsx'

// Everything about one answer, in a drawer: what it cost, where the time
// went, and how it compares with the other answers in this session.
//
// The comparison is the part that earns its place. A single run's numbers are
// hard to judge — 2,719 tokens is neither good nor bad on its own. Against the
// other runs of the same model, and against the other models you have tried,
// it becomes a decision you can act on.

const fmt = new Intl.NumberFormat()
const secs = (n) => `${(n / 1000).toFixed(1)}s`
const pct = (part, whole) => (whole > 0 ? Math.round((part / whole) * 100) : 0)

export default function RunDetails({ open, run, trace, runs = [], onClose }) {
  // Escape closes, like any drawer.
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open || !run) return null

  const totalTokens = run.input_tokens + run.output_tokens
  const rate = run.model_ms > 0 ? Math.round((run.output_tokens / run.model_ms) * 1000) : 0
  const toolShare = pct(run.tool_ms, run.total_ms)

  return (
    <>
      <div className="scrim scrim--details" onClick={onClose} />

      <aside className="details" role="dialog" aria-label="Run details">
        <header className="details__head">
          <div>
            <h2>This answer</h2>
            <p className="details__sub">
              {run.provider} · {run.model}
              {run.effort ? ` · effort ${run.effort}` : ''}
            </p>
          </div>
          <button className="ghost" onClick={onClose} aria-label="Close details">✕</button>
        </header>

        <div className="details__body">
          <Tiles run={run} totalTokens={totalTokens} rate={rate} />

          <Section title="Where the time went" hint="Only the model half is the provider's doing — the tool half is your own code.">
            <SplitBar
              parts={[
                { label: 'model', value: run.model_ms, tone: 'a' },
                { label: 'tools', value: run.tool_ms, tone: 'b' },
              ]}
              total={run.total_ms}
              format={secs}
            />
          </Section>

          <Section title="What you paid for" hint="Reasoning is billed as output but never shown; cached input is billed less.">
            <SplitBar
              parts={[
                { label: 'input', value: run.input_tokens - (run.cached_tokens || 0), tone: 'a' },
                ...(run.cached_tokens ? [{ label: 'cached', value: run.cached_tokens, tone: 'c' }] : []),
                { label: 'output', value: run.output_tokens - (run.reasoning_tokens || 0), tone: 'b' },
                ...(run.reasoning_tokens ? [{ label: 'reasoning', value: run.reasoning_tokens, tone: 'd' }] : []),
              ]}
              total={totalTokens}
              format={fmt.format}
            />
          </Section>

          <Section title="What this tells you">
            <Observations run={run} rate={rate} toolShare={toolShare} runs={runs} />
          </Section>

          {runs.length > 1 && (
            <Section title="Across this session" hint="Averages per model, so you can see which setup actually suits the work.">
              <ModelTable runs={runs} current={run} />
            </Section>
          )}

          {trace?.length > 0 && (
            <Section title="Step by step" hint="One answer, but several round-trips. The gaps are where the time hid.">
              <AgentTrace steps={trace} defaultOpen />
            </Section>
          )}
        </div>
      </aside>
    </>
  )
}

/* ── headline numbers ─────────────────────────────────────── */
function Tiles({ run, totalTokens, rate }) {
  const tiles = [
    ['tokens', fmt.format(totalTokens), `${fmt.format(run.input_tokens)} in · ${fmt.format(run.output_tokens)} out`],
    ['time', secs(run.total_ms), `${secs(run.model_ms)} model · ${secs(run.tool_ms)} tools`],
    ['speed', `${rate}/s`, 'output tokens per second of model time'],
    ['cost', run.cost_usd == null ? '—' : `$${run.cost_usd.toFixed(5)}`,
      run.cost_usd == null ? 'model missing from pricing.py' : 'estimated'],
    ['requests', `${run.model_requests}×`, run.model_requests > 1 ? 'the loop ran' : 'single call'],
    ['tools', run.tool_calls ? `${run.tool_calls}×` : '—', run.search_backend || 'none used'],
  ]
  return (
    <dl className="tiles">
      {tiles.map(([k, v, hint]) => (
        <div key={k} className="tiles__cell">
          <dt>{k}</dt>
          <dd>{v}</dd>
          <span>{hint}</span>
        </div>
      ))}
    </dl>
  )
}

function Section({ title, hint, children }) {
  return (
    <section className="dsec">
      <h3>{title}</h3>
      {hint && <p className="dsec__hint">{hint}</p>}
      {children}
    </section>
  )
}

/* ── proportion bar ───────────────────────────────────────── */
function SplitBar({ parts, total, format }) {
  const shown = parts.filter((p) => p.value > 0)
  return (
    <div className="split">
      <div className="split__bar">
        {shown.map((p) => (
          <span
            key={p.label}
            className={`split__seg split__seg--${p.tone}`}
            style={{ width: `${pct(p.value, total)}%` }}
            title={`${p.label}: ${format(p.value)}`}
          />
        ))}
      </div>
      <ul className="split__key">
        {shown.map((p) => (
          <li key={p.label}>
            <i className={`split__dot split__dot--${p.tone}`} />
            {p.label} <b>{format(p.value)}</b>
            <span>{pct(p.value, total)}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ── plain-language findings ──────────────────────────────── */
function Observations({ run, rate, toolShare, runs }) {
  const notes = []

  if (run.tool_calls > 0) {
    notes.push(
      toolShare >= 40
        ? ['slow', `Tools ate ${toolShare}% of the wait. The model itself only ran for ${secs(run.model_ms)} — speeding this up means a faster search, not a faster model.`]
        : ['ok', `Tools took ${toolShare}% of the wait (${secs(run.tool_ms)}). The model is the bottleneck here, not the search.`],
    )
  }

  if (run.model_requests > 1) {
    notes.push(['info', `${run.model_requests} requests for one answer: the model asked for a tool, read the result, then wrote. You are billed for the conversation again on each pass, which is why input tokens climb.`])
  }

  if (run.reasoning_tokens > 0) {
    const share = pct(run.reasoning_tokens, run.output_tokens)
    notes.push([
      share >= 50 ? 'slow' : 'info',
      `${share}% of output tokens were reasoning you never see. Lowering effort is the lever if that is not paying for itself.`,
    ])
  }

  if (run.cached_tokens > 0) {
    notes.push(['good', `${pct(run.cached_tokens, run.input_tokens)}% of the prompt was served from cache, billed at a lower rate. Keeping the system prompt stable is what earns this.`])
  }

  // Compare against previous runs of the same model.
  const peers = runs.filter((r) => r.model === run.model && r !== run)
  if (peers.length) {
    const avgRate = avg(peers.map((r) => (r.model_ms > 0 ? (r.output_tokens / r.model_ms) * 1000 : 0)))
    if (avgRate > 0 && rate > 0) {
      const delta = Math.round(((rate - avgRate) / avgRate) * 100)
      if (Math.abs(delta) >= 15) {
        notes.push([
          delta > 0 ? 'good' : 'slow',
          `${Math.abs(delta)}% ${delta > 0 ? 'faster' : 'slower'} than this model's average in this session (${Math.round(avgRate)}/s). One-off variance is normal; a run of them is not.`,
        ])
      }
    }
  }

  if (!notes.length) {
    notes.push(['ok', 'A single call, no tools, nothing unusual. This is the cheap path.'])
  }

  return (
    <ul className="notes">
      {notes.map(([tone, text], i) => (
        <li key={i} className={`notes__item notes__item--${tone}`}>{text}</li>
      ))}
    </ul>
  )
}

/* ── per-model averages for the session ───────────────────── */
function ModelTable({ runs, current }) {
  const byModel = new Map()
  for (const r of runs) {
    if (!byModel.has(r.model)) byModel.set(r.model, [])
    byModel.get(r.model).push(r)
  }

  const rows = [...byModel.entries()].map(([model, rs]) => ({
    model,
    runs: rs.length,
    tokens: Math.round(avg(rs.map((r) => r.input_tokens + r.output_tokens))),
    time: avg(rs.map((r) => r.total_ms)),
    rate: Math.round(avg(rs.map((r) => (r.model_ms > 0 ? (r.output_tokens / r.model_ms) * 1000 : 0)))),
    cost: rs.every((r) => r.cost_usd != null) ? avg(rs.map((r) => r.cost_usd)) : null,
  }))

  const cheapest = rows.filter((r) => r.cost != null).sort((a, b) => a.cost - b.cost)[0]
  const fastest = [...rows].sort((a, b) => b.rate - a.rate)[0]

  return (
    <>
      <div className="dtable__wrap">
        <table className="dtable">
          <thead>
            <tr><th>model</th><th>runs</th><th>avg tokens</th><th>avg time</th><th>speed</th><th>avg cost</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.model} className={r.model === current.model ? 'is-current' : ''}>
                <td>{r.model}</td>
                <td>{r.runs}</td>
                <td>{fmt.format(r.tokens)}</td>
                <td>{secs(r.time)}</td>
                <td>{r.rate}/s</td>
                <td>{r.cost == null ? '—' : `$${r.cost.toFixed(5)}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > 1 && (
        <p className="dsec__verdict">
          {fastest && <>Fastest so far: <b>{fastest.model}</b> at {fastest.rate}/s. </>}
          {cheapest ? (
            <>
              Cheapest per answer: <b>{cheapest.model}</b> at ${cheapest.cost.toFixed(5)}.{' '}
              {fastest && fastest.model === cheapest.model
                ? 'Same model wins both — an easy call.'
                : 'Different winners, so it depends on whether latency or cost is what hurts.'}
            </>
          ) : (
            'Cost is unknown for these models — add them to backend/app/pricing.py to compare on price as well as speed.'
          )}
        </p>
      )}
    </>
  )
}

const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)
