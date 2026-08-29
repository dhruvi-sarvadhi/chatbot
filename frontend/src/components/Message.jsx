import Clamped from './Clamped.jsx'
import Markdown from './Markdown.jsx'
import MessageActions from './MessageActions.jsx'
import BotLogo from './BotLogo.jsx'
import Reasoning from './Reasoning.jsx'

// One chat bubble. `role` is "user", "assistant", or "note" (a local-only
// line marking a configuration change — it is never sent to the model).
// "searching" while it runs; "searched:tavily:2310" once a backend has
// answered, so the row itself reports which one ran and how long it took.
function describeSearch(state) {
  if (state === 'searching') return 'Searching the web…'
  const [, backend, ms] = state.split(':')
  if (!backend) return 'Searched the web'
  return `Searched via ${backend} · ${(Number(ms) / 1000).toFixed(1)}s`
}

export default function Message({
  role,
  content,
  meta,
  pending,
  search,
  trace,
  metrics,
  attachments,
  thinking,
  thinkingActive,
  thinkingMs,
  liked,
  onLike,
  onReply,
  onInfo,
}) {
  if (role === 'note') {
    return <div className="note">{content}</div>
  }

  const isUser = role === 'user'

  // The placeholder bubble exists from the moment the request is sent, so
  // until the first thinking / search / answer event it has nothing to show.
  // Rendering it anyway would put a second avatar above the typing dots,
  // which are already the indicator for exactly this moment.
  if (!isUser && pending && !content && !thinking && !search && !trace?.length) return null

  return (
    <div className={`msg ${isUser ? 'msg--user' : 'msg--bot'}`}>
      <div className={`msg__avatar ${isUser ? '' : 'msg__avatar--logo'}`}>
        {isUser ? 'You' : <BotLogo />}
      </div>
      <div className="msg__wrap">
        {attachments?.length > 0 && (
          <ul className="sent">
            {attachments.map((a, i) => (
              <li key={i} className="sent__item">
                <span className="sent__kind">
                  {a.kind === 'image' ? 'IMG' : a.kind === 'document' ? 'PDF' : 'TXT'}
                </span>
                <span className="sent__name">{a.name}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Reasoning sits above the answer because that is the order it
            happened in — the model thought, then it wrote. */}
        {!isUser && search && (
          <div className={`search ${search === 'searching' ? 'search--live' : ''}`}>
            <span className="search__glyph" aria-hidden="true">🌐</span>
            {describeSearch(search)}
          </div>
        )}

        {!isUser && (
          <Reasoning text={thinking} active={thinkingActive} ms={thinkingMs} />
        )}

        {/* No bubble until there is something in it. While the answer is
            still on its way the typing dots are the single indicator — an
            empty bubble here would be a second one saying the same thing. */}
        {(content || (!pending && !thinking)) && (
          <div className="msg__bubble">
            {/* The user's own text is shown verbatim (and capped, with a
                Show more toggle); only model replies are parsed as markdown. */}
            {isUser ? <Clamped text={content} /> : <Markdown>{content}</Markdown>}
            {pending && !thinkingActive && search !== 'searching' && <span className="caret" />}
          </div>
        )}

        {/* Actions appear once there is something to act on — an answer
            still streaming has nothing to copy yet. */}
        {content && !pending && (
          <MessageActions
            text={content}
            isUser={isUser}
            liked={liked}
            onLike={onLike}
            onReply={onReply}
            onInfo={!isUser && metrics ? onInfo : undefined}
          />
        )}

        {/* The model label belongs to an answer, so it waits for one. */}
        {meta && content && <div className="msg__meta">{meta}</div>}
      </div>
    </div>
  )
}
