import { useEffect, useLayoutEffect, useRef, useState } from 'react'

// Custom model picker, replacing the native <select>.
//
// The reason it is worth the code: capabilities are per-model now, and a
// native <option> can only hold a string. Here each row can show whether the
// model reasons and whether it can search — which is exactly what you need to
// know when picking one.
//
// Follows the ARIA listbox pattern: focus stays on the trigger and the active
// row is tracked with aria-activedescendant, so keyboard and screen-reader
// behaviour matches what people expect from a real dropdown.
export default function ModelSelect({ models, value, onChange, id = 'model' }) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const rootRef = useRef(null)
  const listRef = useRef(null)
  const buttonRef = useRef(null)
  const typed = useRef({ text: '', at: 0 })

  const selected = models.find((m) => m.id === value)
  const enabled = (m) => m.available !== false

  // Clicking anywhere else closes it — the behaviour a native select has for
  // free and a div does not.
  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // Open on the current selection rather than at the top of the list.
  useEffect(() => {
    if (!open) return
    const i = models.findIndex((m) => m.id === value)
    setActive(i >= 0 ? i : models.findIndex(enabled))
  }, [open, value, models])

  // Keep the highlighted row visible when arrowing past the fold.
  useLayoutEffect(() => {
    if (!open) return
    listRef.current?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  function choose(m) {
    if (!enabled(m)) return
    onChange(m.id)
    setOpen(false)
    buttonRef.current?.focus()
  }

  /** Next selectable row in `step` direction, skipping unavailable models. */
  function step(from, dir) {
    for (let i = from + dir; i >= 0 && i < models.length; i += dir) {
      if (enabled(models[i])) return i
    }
    return from
  }

  function onKeyDown(e) {
    if (!open) {
      if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(e.key)) {
        e.preventDefault()
        setOpen(true)
      }
      return
    }

    switch (e.key) {
      case 'Escape':
        e.preventDefault()
        setOpen(false)
        buttonRef.current?.focus()
        break
      case 'Tab':
        setOpen(false)
        break
      case 'ArrowDown':
        e.preventDefault()
        setActive((i) => step(i, 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setActive((i) => step(i, -1))
        break
      case 'Home':
        e.preventDefault()
        setActive(models.findIndex(enabled))
        break
      case 'End':
        e.preventDefault()
        setActive(step(models.length, -1))
        break
      case 'Enter':
      case ' ':
        e.preventDefault()
        if (models[active]) choose(models[active])
        break
      default:
        // Type-ahead: "h" jumps to Haiku. Keystrokes within a second of each
        // other build up a prefix, the way a native select behaves.
        if (e.key.length !== 1 || e.metaKey || e.ctrlKey || e.altKey) return
        const now = Date.now()
        typed.current.text = now - typed.current.at > 1000 ? e.key : typed.current.text + e.key
        typed.current.at = now
        const q = typed.current.text.toLowerCase()
        const hit = models.findIndex((m) => enabled(m) && m.label.toLowerCase().startsWith(q))
        if (hit >= 0) setActive(hit)
    }
  }

  return (
    <div className="ms" ref={rootRef}>
      <button
        type="button"
        id={id}
        ref={buttonRef}
        className={`ms__trigger ${open ? 'is-open' : ''}`}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-activedescendant={open && models[active] ? `${id}-opt-${active}` : undefined}
      >
        <span className="ms__value">
          <span className="ms__name">{selected ? selected.label : value}</span>
          <span className="ms__hint">{selected ? selected.hint : 'custom id'}</span>
        </span>
        <svg className="ms__caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor"
                strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <ul className="ms__list" role="listbox" ref={listRef} aria-labelledby={id}>
          {models.map((m, i) => {
            const off = !enabled(m)
            return (
              <li
                key={m.id}
                id={`${id}-opt-${i}`}
                role="option"
                aria-selected={m.id === value}
                aria-disabled={off}
                data-active={i === active}
                className={`ms__opt ${off ? 'is-off' : ''} ${m.id === value ? 'is-selected' : ''}`}
                onMouseEnter={() => !off && setActive(i)}
                onClick={() => choose(m)}
              >
                <span className="ms__optmain">
                  <span className="ms__name">{m.label}</span>
                  <span className="ms__hint">{m.hint}</span>
                </span>
                <span className="ms__tags">
                  {off && <span className="ms__tag ms__tag--off">not on your key</span>}
                  {!off && m.supports_thinking && <span className="ms__tag">reasons</span>}
                  {!off && m.supports_search && <span className="ms__tag">web</span>}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
