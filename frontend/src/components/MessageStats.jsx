// What one answer cost. Sits under the reply as a quiet strip, because it is
// something you glance at rather than read.
//
// The pairs that matter most are the ones that split a single number in two:
// output vs reasoning tokens (you pay for both, you only see one), and model
// time vs tool time (only one of those is yours to optimise).

const fmt = new Intl.NumberFormat()
const secs = (n) => `${(n / 1000).toFixed(1)}s`

export default function MessageStats({ m }) {
  if (!m) return null

  const total = m.input_tokens + m.output_tokens
  // Output tokens per second of model time — the honest throughput number,
  // since tool time is not the model being slow.
  const rate = m.model_ms > 0 ? Math.round((m.output_tokens / m.model_ms) * 1000) : 0
  const toolShare = m.total_ms > 0 ? Math.round((m.tool_ms / m.total_ms) * 100) : 0

  const cells = [
    ['tokens', fmt.format(total), `${fmt.format(m.input_tokens)} in · ${fmt.format(m.output_tokens)} out`],
    ...(m.reasoning_tokens > 0
      ? [['reasoning', fmt.format(m.reasoning_tokens), 'billed as output, never shown']]
      : []),
    ...(m.cached_tokens > 0
      ? [['cached', fmt.format(m.cached_tokens), 'prompt prefix reused, billed less']]
      : []),
    ['time', secs(m.total_ms), `${secs(m.model_ms)} model · ${secs(m.tool_ms)} tools`],
    ['speed', `${rate}/s`, 'output tokens per second of model time'],
    ...(m.tool_calls > 0
      ? [['tools', `${m.tool_calls}×`, `${m.search_backend || 'tool'} · ${toolShare}% of the wait`]]
      : []),
    ['requests', `${m.model_requests}×`, m.model_requests > 1 ? 'the loop ran' : 'single call'],
    [
      'cost',
      m.cost_usd == null ? '—' : `$${m.cost_usd.toFixed(5)}`,
      m.cost_usd == null ? 'add this model to backend/app/pricing.py' : 'estimated from pricing.py',
    ],
  ]

  return (
    <dl className="stats">
      {cells.map(([label, value, title]) => (
        <div key={label} className="stats__cell" title={title}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
