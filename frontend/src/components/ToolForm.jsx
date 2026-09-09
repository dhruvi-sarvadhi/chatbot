import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * The card the model shows instead of asking for fields one at a time.
 *
 * The spec comes from the backend (`tools/ask_form.py`) and already carries
 * real options — this project's statuses, this project's team — so a dropdown
 * here cannot produce a value the API will reject. This component renders it
 * and hands the answers back; it decides nothing about which fields exist.
 *
 * Two hints in the spec drive the layout, so the UI never has to guess from a
 * field's name: `span` ("half" / "full") places it in the two-column grid, and
 * `style` picks the control. A status is a handful of fixed choices, so it
 * becomes a row of buttons you can hit in one click rather than a dropdown you
 * have to open, aim inside, and close.
 *
 * Values are held as strings because that is what DOM inputs give us;
 * `submitValues` puts the numbers back on the way out, so the model receives
 * `task_status_id: 5` and not `"5"`.
 */
export default function ToolForm({ spec, state = 'closed', onSubmit, onCancel }) {
  const active = state === 'open'
  const fields = spec?.fields ?? []

  const [values, setValues] = useState(() =>
    Object.fromEntries(fields.map((f) => [f.name, f.value != null ? String(f.value) : ''])),
  )
  const [touched, setTouched] = useState(false)
  const firstInput = useRef(null)

  // A field is only missing if it is required AND empty. Optional pickers are
  // deliberately blank — "no status" means "let Clarix use its default".
  const missing = useMemo(
    () => fields.filter((f) => f.required && !String(values[f.name] ?? '').trim()),
    [fields, values],
  )

  // Focus the first field the moment the card becomes fillable — which is when
  // the answer finishes streaming, not when the card appears. Doing it earlier
  // would yank the caret out of the composer mid-sentence.
  useEffect(() => {
    if (active) firstInput.current?.focus()
  }, [active])

  if (!spec) return null

  function set(name, value) {
    setValues((prev) => ({ ...prev, [name]: value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    setTouched(true)
    if (missing.length) return
    onSubmit(submitValues(spec, values))
  }

  // ⌘/Ctrl+Enter submits from anywhere, including the description box — where
  // plain Enter has to keep meaning "new line".
  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e)
  }

  return (
    <form
      className={`toolform ${active ? '' : 'toolform--closed'}`}
      onSubmit={handleSubmit}
      onKeyDown={handleKeyDown}
    >
      <header className="toolform__head">
        <FormIcon kind={spec.kind} />
        <h3 className="toolform__title">{spec.title}</h3>
        {(spec.context?.task_name || spec.context?.project_name) && (
          <span className="toolform__tag">
            {spec.context.task_name || spec.context.project_name}
          </span>
        )}
      </header>

      <div className="toolform__body">
        {fields.map((field, i) => (
          <Field
            key={field.name}
            field={field}
            id={`${spec.id}-${field.name}`}
            value={values[field.name] ?? ''}
            invalid={touched && field.required && !String(values[field.name] ?? '').trim()}
            disabled={!active}
            inputRef={i === 0 ? firstInput : undefined}
            onChange={(v) => set(field.name, v)}
          />
        ))}
      </div>

      {active && (
        <footer className="toolform__foot">
          {touched && missing.length > 0 ? (
            <span className="toolform__error">
              {missing.map((f) => f.label).join(' and ')} {missing.length > 1 ? 'are' : 'is'} required
            </span>
          ) : (
            <span className="toolform__shortcut">
              <kbd>{isMac() ? '⌘' : 'Ctrl'}</kbd>
              <kbd>↵</kbd>
              to submit
            </span>
          )}
          <button type="button" className="ghost" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="toolform__submit">
            {spec.submit_label || 'Send'}
          </button>
        </footer>
      )}

      {/* A closed form keeps its footer bare rather than claiming "Submitted":
          the turn may have moved on because the user typed something else
          entirely, and the card cannot tell. Only a dismissal is stated,
          because that one is unambiguous. */}
      {state === 'cancelled' && (
        <footer className="toolform__foot toolform__foot--quiet">Dismissed</footer>
      )}
    </form>
  )
}

/** One labelled control. Which control is the spec's call, not this file's. */
function Field({ field, id, value, invalid, disabled, inputRef, onChange }) {
  const pills = field.style === 'status' && (field.options?.length ?? 0) <= 6
  const cls = `toolform__field toolform__field--${field.span === 'half' ? 'half' : 'full'}`

  return (
    <div className={cls}>
      <label className="toolform__label" htmlFor={pills ? undefined : id}>
        {field.label}
        {field.required && <span className="toolform__req" aria-hidden="true">*</span>}
      </label>

      {pills ? (
        <Pills field={field} name={id} value={value} disabled={disabled} onChange={onChange} />
      ) : field.type === 'select' ? (
        <div className="toolform__picker">
          {field.style === 'people' && value && <Avatar label={labelFor(field, value)} />}
          <select
            id={id}
            ref={inputRef}
            className={`toolform__input toolform__input--select ${invalid ? 'is-bad' : ''} ${
              field.style === 'people' && value ? 'toolform__input--inset' : ''
            }`}
            value={value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">{field.placeholder || '—'}</option>
            {field.options?.map((o) => (
              <option key={String(o.value)} value={String(o.value)}>
                {o.label}
              </option>
            ))}
          </select>
          <Chevron />
        </div>
      ) : field.type === 'textarea' ? (
        <textarea
          id={id}
          ref={inputRef}
          className={`toolform__input toolform__input--area ${invalid ? 'is-bad' : ''}`}
          rows={3}
          value={value}
          disabled={disabled}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          id={id}
          ref={inputRef}
          className={`toolform__input ${invalid ? 'is-bad' : ''}`}
          type="text"
          value={value}
          disabled={disabled}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {field.hint && <span className="toolform__hint">{field.hint}</span>}
    </div>
  )
}

/**
 * A short fixed set of choices as buttons rather than a dropdown.
 *
 * Radio inputs, not divs with click handlers: arrow keys move between them and
 * a screen reader announces the group, both for free. The input is hidden but
 * still focusable, and the visible pill is its label.
 */
function Pills({ field, name, value, disabled, onChange }) {
  const choices = [{ value: '', label: field.placeholder || 'Default' }, ...(field.options ?? [])]

  return (
    <div className="toolform__pills">
      {choices.map((choice) => {
        const raw = String(choice.value)
        const on = raw === value
        return (
          <label key={raw || '_'} className={`toolform__pill ${on ? 'is-on' : ''}`}>
            <input
              type="radio"
              name={name}
              value={raw}
              checked={on}
              disabled={disabled}
              onChange={() => onChange(raw)}
            />
            {raw !== '' && (
              <span className="toolform__dot" style={{ background: statusColor(choice.label) }} />
            )}
            {choice.label}
          </label>
        )
      })}
    </div>
  )
}

function Avatar({ label }) {
  return (
    <span
      className="toolform__avatar"
      style={{ background: `hsl(${hueOf(label)} 55% 45%)` }}
      aria-hidden="true"
    >
      {initials(label)}
    </span>
  )
}

function Chevron() {
  return (
    <svg className="toolform__chevron" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function FormIcon({ kind }) {
  // A checklist for a task, a folder for a project, a speech bubble for a
  // comment — enough to tell them apart at a glance when more than one turns
  // up in the same conversation.
  const path =
    kind === 'create_project'
      ? 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z'
      : kind === 'add_comment'
        ? 'M4 5h16v11H9l-5 4Z'
        : 'M9 5h11M9 12h11M9 19h11M3.5 5 4.7 6.2 7 4M3.5 12l1.2 1.2L7 11M3.5 19l1.2 1.2L7 18'
  return (
    <svg className="toolform__icon" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── small helpers ───────────────────────────────────────────────────────────

const isMac = () => typeof navigator !== 'undefined' && /Mac|iP(hone|ad)/.test(navigator.userAgent)

function labelFor(field, value) {
  return field.options?.find((o) => String(o.value) === value)?.label ?? ''
}

function initials(label) {
  const parts = String(label).trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (parts[0][0] + last).toUpperCase()
}

/**
 * Same name, same colour, every render and every session.
 *
 * The range skips the reds either side of 0: an avatar is an identity, and a
 * red circle inside a form reads as something being wrong with the field.
 */
function hueOf(text) {
  let h = 0
  for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) % 310
  return 25 + h
}

/**
 * A dot colour for a status pill.
 *
 * Workflow words carry meaning people already know — done is green, blocked is
 * red — so those are worth matching rather than randomising. Anything else
 * falls back to a stable colour derived from the name, which at least stays
 * the same every time you see that status.
 */
const STATUS_HUES = [
  [/(done|complete|closed|resolved|finish)/i, 142],
  [/(block|hold|reject|cancel|fail)/i, 4],
  [/(review|qa|test|verify)/i, 275],
  [/(progress|doing|active|develop|start)/i, 38],
  [/(to.?do|backlog|open|new|pending)/i, 220],
]

function statusColor(label) {
  const hit = STATUS_HUES.find(([re]) => re.test(String(label)))
  return `hsl(${hit ? hit[1] : hueOf(label)} 65% 50%)`
}

/**
 * The filled-in form as a message the model can act on.
 *
 * Written as `key: value` lines rather than prose because the model has to
 * copy these straight into a `clarix_projects` call — an id in a sentence is
 * an id it can paraphrase. Keys are the tool's own parameter names for the
 * same reason. Ids that came from a picker are sent as numbers with the human
 * label alongside, so the reply can name the status the user picked.
 *
 * Blank fields are omitted rather than sent empty: `description: ""` on an
 * update would blank a real description, and the tool cannot tell "leave it"
 * from "clear it" once it is in the message.
 */
export function submitValues(spec, values) {
  const lines = []

  for (const [key, val] of Object.entries(spec.context ?? {})) {
    // Whatever the user chose in the form beats what the tool inferred.
    if (String(values[key] ?? '').trim()) continue
    // A padded `task_id: 0` is worse than no task_id at all — it reads as a
    // real id. The backend drops these too; this covers a spec built before
    // it did.
    if (String(val).trim() === '0') continue
    lines.push(`- ${key}: ${val}`)
  }

  for (const field of spec.fields ?? []) {
    const raw = String(values[field.name] ?? '').trim()
    if (!raw) continue

    if (field.type === 'select') {
      const picked = field.options?.find((o) => String(o.value) === raw)
      lines.push(`- ${field.name}: ${picked?.value ?? raw}  (${picked?.label ?? raw})`)
    } else if (raw.includes('\n')) {
      // A multi-line answer cannot share a `- key: value` line — the model
      // copies the first line into the tool call and drops the rest. A block
      // scalar keeps the paragraph together, which matters most for a comment,
      // where the text is posted exactly as written.
      const body = raw.split('\n').map((l) => `    ${l}`).join('\n')
      lines.push(`- ${field.name}: |\n${body}`)
    } else {
      lines.push(`- ${field.name}: ${raw}`)
    }
  }

  const verb =
    spec.kind === 'create_task'
      ? 'Create the task'
      : spec.kind === 'create_project'
        ? 'Create the project'
        : spec.kind === 'add_comment'
          ? 'Post this comment on the task'
          : 'Update the task'

  // The tool and action are NAMED, not implied. Told only to "create the task
  // with these details", gpt-4o-mini went and searched the web for
  // "Week-september-task-list" until it hit the tool-turn limit. Every form
  // kind is also the name of the clarix_projects action that writes it, which
  // is what makes this one line rather than another lookup table.
  return [
    `${verb} now by calling the clarix_projects tool with action="${spec.kind}" and exactly these values.`,
    'They are already resolved: use them as given, do not look anything up, do not search the web, and do not ask me anything else.',
    ...lines,
  ].join('\n')
}
