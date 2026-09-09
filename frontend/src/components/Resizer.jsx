import { useCallback, useEffect, useState } from 'react'

/**
 * A draggable edge that resizes the panel next to it.
 *
 * Pointer events rather than mouse events, so a trackpad, a touchscreen and a
 * pen all work from one code path. `setPointerCapture` is the important part:
 * once the drag starts, moves keep arriving at this element even when the
 * cursor runs ahead of it or leaves the window — without it a fast drag drops
 * the handle the moment the pointer outpaces the re-render.
 *
 * Dragging most of the way shut collapses rather than leaving an unusable
 * sliver, and dragging back out from collapsed reopens. That makes the handle
 * the whole control: no separate button needed to get the panel back, though
 * the header has one anyway for people who never think to drag an edge.
 *
 * It is also a real `separator` widget: arrow keys nudge it, Home/End jump to
 * the extremes, and Enter toggles collapse — a resize you cannot do without a
 * mouse is one some people simply cannot do.
 */
export default function Resizer({
  width,
  onWidth,
  collapsed = false,
  onCollapsed,
  min = 220,
  max = 560,
  // Which side of the screen the panel is pinned to. That decides whether a
  // pointer at x=400 means "400 wide" or "everything to the right of 400".
  side = 'left',
  label = 'Resize panel',
  className = '',
}) {
  const [dragging, setDragging] = useState(false)

  // The ceiling is whichever is smaller: the caller's max, or half the window.
  // A sidebar that can eat the conversation is not a feature.
  const ceiling = useCallback(
    () => Math.max(min, Math.min(max, Math.round(window.innerWidth * 0.5))),
    [min, max],
  )

  // A stored width from a wider window must not survive into a narrow one.
  useEffect(() => {
    const clamp = () => {
      const top = ceiling()
      if (width > top) onWidth(top)
    }
    window.addEventListener('resize', clamp)
    return () => window.removeEventListener('resize', clamp)
  }, [width, onWidth, ceiling])

  // Belt and braces: if a pointerup is ever missed (a dropped capture, a
  // context menu), the body must not be left stuck in resize mode.
  useEffect(() => {
    if (!dragging) return
    document.body.classList.add('is-resizing')
    return () => document.body.classList.remove('is-resizing')
  }, [dragging])

  const apply = (raw) => {
    // Below this the panel is too narrow to read, so the gesture means close —
    // but only where closing is a thing this panel does. A drawer with no
    // collapse must stop at its floor instead, or dragging hard left just
    // freezes it and looks broken.
    if (raw < min * 0.6 && onCollapsed) {
      onCollapsed(true)
      return
    }
    onCollapsed?.(false)
    onWidth(Math.min(ceiling(), Math.max(min, raw)))
  }

  function handleDown(e) {
    if (e.button != null && e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragging(true)
  }

  function handleMove(e) {
    if (!dragging) return
    apply(side === 'left' ? e.clientX : window.innerWidth - e.clientX)
  }

  function handleUp(e) {
    if (!dragging) return
    e.currentTarget.releasePointerCapture?.(e.pointerId)
    setDragging(false)
  }

  function handleKey(e) {
    const step = e.shiftKey ? 48 : 16
    // "Wider" is a different arrow key depending on which edge you are on.
    const grow = side === 'left' ? 'ArrowRight' : 'ArrowLeft'
    const shrink = side === 'left' ? 'ArrowLeft' : 'ArrowRight'

    if (e.key === grow) apply((collapsed ? 0 : width) + step)
    else if (e.key === shrink) apply((collapsed ? 0 : width) - step)
    else if (e.key === 'Home') apply(min)
    else if (e.key === 'End') apply(ceiling())
    else if (e.key === 'Enter' || e.key === ' ') onCollapsed?.(!collapsed)
    else return

    e.preventDefault()
  }

  return (
    <div
      className={`resizer ${dragging ? 'is-dragging' : ''} ${collapsed ? 'is-collapsed' : ''} ${className}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={collapsed ? 0 : width}
      aria-valuemin={0}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={handleDown}
      onPointerMove={handleMove}
      onPointerUp={handleUp}
      onPointerCancel={handleUp}
      onDoubleClick={() => onCollapsed?.(!collapsed)}
      onKeyDown={handleKey}
      title="Drag to resize · double-click to collapse"
    >
      <span className="resizer__grip" aria-hidden="true" />
    </div>
  )
}

/**
 * A width the browser remembers, so the layout you set up is the layout you
 * come back to. Falls back to `initial` when nothing is stored or the stored
 * value is junk — a corrupt entry should not leave a 0px sidebar with no
 * obvious way back.
 */
export function useStoredWidth(key, initial) {
  const [width, setWidth] = useState(() => {
    const stored = Number(localStorage.getItem(key))
    return Number.isFinite(stored) && stored > 0 ? stored : initial
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, String(width))
    } catch {
      // A full or blocked store is not worth breaking the layout over.
    }
  }, [key, width])

  return [width, setWidth]
}

/** The same, for a boolean. Kept here so the pair stays in one place. */
export function useStoredFlag(key, initial = false) {
  const [on, setOn] = useState(() => {
    const stored = localStorage.getItem(key)
    return stored == null ? initial : stored === '1'
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, on ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [key, on])

  return [on, setOn]
}
