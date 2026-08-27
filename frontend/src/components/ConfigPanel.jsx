import { THEMES } from '../lib/theme.js'
import ModelSelect from './ModelSelect.jsx'

// Left-hand configuration panel. Everything here is sent with the *next*
// message, so changes take effect immediately — no restart, no page reload.


const BACKEND_LABEL = {
  auto: 'Auto',
  tavily: 'Tavily',
  duckduckgo: 'DuckDuckGo',
  compare: 'Compare both',
}

const BACKEND_HINT = {
  auto: 'Tavily when a key is set, otherwise DuckDuckGo.',
  tavily: 'Search API built for LLMs. Returns extracted text and a summary — one call, ~2s.',
  duckduckgo: 'Free, no key. Snippets only, so it also opens the top pages to read them — ~8s.',
  compare: 'Runs both and times them. Twice the cost; the trace panel shows the difference.',
}

const TOKEN_STEPS = [256, 512, 1024, 2048, 4096, 8192, 16000]

export default function ConfigPanel({ schema, config, onChange, onReset, usage, runs = [], open, onClose, theme, onThemeChange }) {
  if (!schema) {
    return (
      <aside className={`panel ${open ? 'panel--open' : ''}`}>
        <p className="panel__loading">Loading configuration…</p>
      </aside>
    )
  }

  const provider = schema.providers.find((p) => p.id === config.provider) ?? schema.providers[0]
  // Reasoning and search are per-model, not per-provider: Haiku 4.5 rejects
  // the effort parameter that Opus 5 requires, and GPT-4o does not reason.
  // A hand-typed id is not in the list, so assume the current generation.
  const model = provider.models.find((m) => m.id === config.model)
  const canEffort = model ? model.supports_effort : provider.supports_effort
  const canSearch = model ? model.supports_search : true
  const set = (patch) => onChange({ ...config, ...patch })

  function switchProvider(next) {
    // Each provider has its own model list — move to that provider's first
    // usable model instead of carrying an incompatible id across.
    const first = next.models.find((m) => m.available !== false) ?? next.models[0]
    set({ provider: next.id, model: first.id })
  }

  return (
    <aside className={`panel ${open ? 'panel--open' : ''}`}>
      <div className="panel__head">
        <h2>Configuration</h2>
        <button className="ghost panel__close" onClick={onClose} aria-label="Close settings">
          ✕
        </button>
      </div>

      <div className="panel__body">
        {/* ── Which API ───────────────────────────────────────── */}
        <section className="field">
          <label className="field__label">API provider</label>
          <div className="segmented">
            {schema.providers.map((p) => (
              <button
                key={p.id}
                className={`segmented__item ${p.id === config.provider ? 'is-active' : ''}`}
                onClick={() => switchProvider(p)}
                disabled={!p.api_key_configured}
                title={p.api_key_configured ? p.vendor : `No API key for ${p.label} in backend/.env`}
              >
                {p.label}
                {!p.api_key_configured && <span className="segmented__warn">no key</span>}
              </button>
            ))}
          </div>
          <p className="field__hint">Calls go to {provider.vendor}. The key stays on the server.</p>
        </section>

        {/* ── Model ───────────────────────────────────────────── */}
        <section className="field">
          <label className="field__label" htmlFor="model">Model</label>
          {/* Custom listbox rather than a native <select>: an <option> can
              only hold a string, and each row needs to show whether the model
              reasons and whether it can search. */}
          <ModelSelect
            models={provider.models}
            value={config.model}
            onChange={(id) => set({ model: id })}
          />
          <input
            className="field__custom"
            value={config.model}
            onChange={(e) => set({ model: e.target.value })}
            placeholder="or type any model id"
            spellCheck={false}
          />
        </section>

        {/* ── Effort (Claude only) ────────────────────────────── */}
        <section className={`field ${canEffort ? '' : 'field--off'}`}>
          <label className="field__label">
            Thinking effort
            {!canEffort && <span className="field__tag">not on this model</span>}
          </label>
          <div className="segmented segmented--small">
            {schema.effort_levels.map((level) => (
              <button
                key={level}
                className={`segmented__item ${level === config.effort ? 'is-active' : ''}`}
                onClick={() => set({ effort: level })}
                disabled={!canEffort}
              >
                {level}
              </button>
            ))}
          </div>
          <p className="field__hint">
            How long the model thinks before answering. Higher = better, slower, pricier.
          </p>
        </section>

        {/* ── Live data ───────────────────────────────────────── */}
        <section className={`field ${canSearch ? '' : 'field--off'}`}>
          <label className="field__label">
            Live data
            {!canSearch && <span className="field__tag">not on this model</span>}
          </label>
          <label className="toggle toggle--block">
            <input
              type="checkbox"
              checked={Boolean(config.web_search)}
              disabled={!canSearch}
              onChange={(e) => set({ web_search: e.target.checked })}
            />
            Let the model search the web
          </label>
          <p className="field__hint">
            Prices, news, anything after the training cutoff. Your backend runs the
            search itself, so it is slower and costs the tokens the results take up.
          </p>

          {config.web_search && canSearch && (
            <div className="subfield">
              <label className="field__label field__label--sub" htmlFor="backend">
                Search backend
              </label>
              <div className="segmented segmented--small segmented--wrap">
                {(schema.search_backends ?? ['auto']).map((b) => {
                  const needsKey = b !== 'duckduckgo' && b !== 'auto' && !schema.tavily_configured
                  return (
                    <button
                      key={b}
                      className={`segmented__item ${b === (config.search_backend ?? 'auto') ? 'is-active' : ''}`}
                      onClick={() => set({ search_backend: b })}
                      disabled={needsKey}
                      title={needsKey ? 'Set TAVILY_API_KEY in backend/.env' : BACKEND_HINT[b]}
                    >
                      {BACKEND_LABEL[b] ?? b}
                    </button>
                  )
                })}
              </div>
              <p className="field__hint">
                {BACKEND_HINT[config.search_backend ?? 'auto']}
                {!schema.tavily_configured && ' No TAVILY_API_KEY set, so DuckDuckGo is used.'}
              </p>
            </div>
          )}
        </section>

        {/* ── Max tokens ──────────────────────────────────────── */}
        <section className="field">
          <label className="field__label" htmlFor="tokens">
            Max output tokens <span className="field__value">{config.max_tokens}</span>
          </label>
          <input
            id="tokens"
            type="range"
            min={0}
            max={TOKEN_STEPS.length - 1}
            step={1}
            value={Math.max(0, TOKEN_STEPS.indexOf(nearestStep(config.max_tokens)))}
            onChange={(e) => set({ max_tokens: TOKEN_STEPS[Number(e.target.value)] })}
          />
          <p className="field__hint">Hard ceiling on the answer length for one reply.</p>
        </section>

        {/* ── System prompt ───────────────────────────────────── */}
        <section className="field">
          <label className="field__label" htmlFor="system">System prompt</label>
          <textarea
            id="system"
            rows={5}
            value={config.system_prompt}
            onChange={(e) => set({ system_prompt: e.target.value })}
            placeholder="You are a helpful assistant."
          />
          <p className="field__hint">
            The standing instruction sent ahead of every message. Edit it and send —
            the bot changes personality on the next reply.
          </p>
        </section>

        {/* ── Appearance ──────────────────────────────────────── */}
        <section className="field">
          <label className="field__label">Appearance</label>
          <div className="segmented segmented--small">
            {THEMES.map((t) => (
              <button
                key={t}
                className={`segmented__item ${t === theme ? 'is-active' : ''}`}
                onClick={() => onThemeChange(t)}
              >
                {t}
              </button>
            ))}
          </div>
          <p className="field__hint">
            “System” follows your OS setting; the other two override it.
          </p>
        </section>

        {/* ── Session analytics ───────────────────────────────── */}
        {runs.length > 0 && <SessionStats runs={runs} />}

        {/* ── Live readout ────────────────────────────────────── */}
        <section className="readout">
          <div className="readout__row">
            <span>Sending to</span>
            <strong>{provider.label} · {config.model}</strong>
          </div>
          <div className="readout__row">
            <span>Live data</span>
            <strong>
              {config.web_search && canSearch
                ? `web search · ${BACKEND_LABEL[config.search_backend ?? 'auto']}`
                : 'off'}
            </strong>
          </div>
          {usage && (
            <div className="readout__row">
              <span>Last turn</span>
              <strong>{usage.input_tokens} in · {usage.output_tokens} out</strong>
            </div>
          )}
        </section>

        <button className="ghost panel__reset" onClick={onReset}>
          Reset to backend/.env defaults
        </button>
      </div>
    </aside>
  )
}

function nearestStep(value) {
  return TOKEN_STEPS.reduce((best, s) =>
    Math.abs(s - value) < Math.abs(best - value) ? s : best,
  )
}


/** Totals across every answer so far — the session bill, not one turn's. */
function SessionStats({ runs }) {
  const fmt = new Intl.NumberFormat()
  const sum = (f) => runs.reduce((n, r) => n + (f(r) || 0), 0)

  const tokens = sum((r) => r.input_tokens) + sum((r) => r.output_tokens)
  const totalMs = sum((r) => r.total_ms)
  const toolMs = sum((r) => r.tool_ms)
  // Turns with no price for their model would drag an average down to a lie,
  // so cost covers only the priced ones and says how many that was.
  const priced = runs.filter((r) => r.cost_usd != null)
  const cost = priced.reduce((n, r) => n + r.cost_usd, 0)

  const rows = [
    ['Turns', String(runs.length)],
    ['Tokens', fmt.format(tokens)],
    ['Reasoning', fmt.format(sum((r) => r.reasoning_tokens))],
    ['Avg latency', `${(totalMs / runs.length / 1000).toFixed(1)}s`],
    ['In tools', totalMs ? `${Math.round((toolMs / totalMs) * 100)}%` : '0%'],
    [
      'Est. cost',
      priced.length === 0
        ? '—'
        : `$${cost.toFixed(4)}${priced.length < runs.length ? ` (${priced.length}/${runs.length})` : ''}`,
    ],
  ]

  return (
    <section className="field">
      <label className="field__label">This session</label>
      <div className="sess">
        {rows.map(([k, v]) => (
          <div key={k} className="sess__row">
            <span>{k}</span>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <p className="field__hint">
        Resets with Clear. Cost needs the model listed in backend/app/pricing.py.
      </p>
    </section>
  )
}
