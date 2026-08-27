import { useState } from 'react'
import { copyText } from '../lib/clipboard.js'

// Small action row under a bubble.
//   questions — copy, reply
//   answers   — copy, reply, like, share
export default function MessageActions({ text, isUser, liked, onLike, onReply, onInfo }) {
  const [copied, setCopied] = useState(false)
  const [shared, setShared] = useState(null)

  async function handleCopy() {
    const ok = await copyText(text)
    setCopied(ok)
    setTimeout(() => setCopied(false), 1400)
  }

  async function handleShare() {
    // Native share sheet where the browser has one (mobile, Safari); every
    // other browser falls back to putting the text on the clipboard.
    if (navigator.share) {
      try {
        await navigator.share({ title: 'Chatbot answer', text })
        return
      } catch {
        return // user dismissed the sheet — not an error worth showing
      }
    }
    const ok = await copyText(text)
    setShared(ok ? 'Copied to share' : 'Could not copy')
    setTimeout(() => setShared(null), 1600)
  }

  return (
    <div className={`acts ${isUser ? 'acts--user' : ''}`}>
      <button className="acts__btn" onClick={handleCopy} title="Copy" aria-label="Copy message">
        {copied ? <CheckIcon /> : <CopyIcon />}
        <span className="acts__label">{copied ? 'Copied' : 'Copy'}</span>
      </button>

      <button className="acts__btn" onClick={() => onReply(text)} title="Reply" aria-label="Reply to message">
        <ReplyIcon />
        <span className="acts__label">Reply</span>
      </button>

      {!isUser && (
        <>
          <button
            className={`acts__btn ${liked ? 'is-on' : ''}`}
            onClick={onLike}
            title={liked ? 'Remove like' : 'Like'}
            aria-label="Like answer"
            aria-pressed={liked}
          >
            <LikeIcon filled={liked} />
            <span className="acts__label">{liked ? 'Liked' : 'Like'}</span>
          </button>

          <button className="acts__btn" onClick={handleShare} title="Share" aria-label="Share answer">
            <ShareIcon />
            <span className="acts__label">{shared ?? 'Share'}</span>
          </button>

          {onInfo && (
            <button className="acts__btn" onClick={onInfo} title="Run details" aria-label="Run details">
              <InfoIcon />
              <span className="acts__label">Details</span>
            </button>
          )}
        </>
      )}
    </div>
  )
}

/* ── icons: 16px, stroked, inherit colour ─────────────────── */
const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Icon({ children }) {
  return <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">{children}</svg>
}

function CopyIcon() {
  return (
    <Icon>
      <rect x="9" y="9" width="11" height="11" rx="2.5" {...stroke} />
      <path d="M5.5 15H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v.5" {...stroke} />
    </Icon>
  )
}

function CheckIcon() {
  return <Icon><path d="m5 13 4.5 4.5L19 7" {...stroke} strokeWidth={2} /></Icon>
}

function ReplyIcon() {
  return (
    <Icon>
      <path d="M9 8V4.5L3 10l6 5.5V12c4.2 0 7.5 1.6 9.5 5.5C18.7 11 15.5 8 9 8Z" {...stroke} />
    </Icon>
  )
}

function LikeIcon({ filled }) {
  return (
    <Icon>
      <path
        d="M7 10.5v9H4.5a.5.5 0 0 1-.5-.5v-8a.5.5 0 0 1 .5-.5H7Zm0 0 4-7a2.2 2.2 0 0 1 2.2 2.9L12.4 9H18a1.8 1.8 0 0 1 1.8 2.2l-1.3 6.3a2 2 0 0 1-2 1.5H7"
        {...stroke}
        fill={filled ? 'currentColor' : 'none'}
      />
    </Icon>
  )
}

function InfoIcon() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="8.5" {...stroke} />
      <path d="M12 11v5.5" {...stroke} />
      <circle cx="12" cy="8" r="1" fill="currentColor" stroke="none" />
    </Icon>
  )
}

function ShareIcon() {
  return (
    <Icon>
      <circle cx="17.5" cy="5.5" r="2.5" {...stroke} />
      <circle cx="6.5" cy="12" r="2.5" {...stroke} />
      <circle cx="17.5" cy="18.5" r="2.5" {...stroke} />
      <path d="m8.8 10.8 6.4-3.6M8.8 13.2l6.4 3.6" {...stroke} />
    </Icon>
  )
}
