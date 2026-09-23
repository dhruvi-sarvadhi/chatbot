import Clamped from './Clamped.jsx'
import Markdown from './Markdown.jsx'
import MessageActions from './MessageActions.jsx'
import BotLogo from './BotLogo.jsx'
import Reasoning from './Reasoning.jsx'
import ToolForm from './ToolForm.jsx'

// One chat bubble. `role` is "user", "assistant", or "note" (a local-only
// line marking a configuration change — it is never sent to the model).
// "searching" while it runs; "searched:tavily:2310" once a backend has
// answered, so the row itself reports which one ran and how long it took.
function describeSearch(state) {
  if (state === 'searching') return 'Searching the web…'
  if (state === 'drawing') return 'Drawing…'
  if (state === 'drew') return 'Image generated'
  const [, backend, ms] = state.split(':')
  if (!backend) return 'Searched the web'
  return `Searched via ${backend} · ${(Number(ms) / 1000).toFixed(1)}s`
}

// Drawing borrows the search row rather than adding a second status line —
// both answer the same question ("what is it doing during this pause?").
const DRAWING = new Set(['drawing', 'drew'])

function glyphFor(state) {
  return DRAWING.has(state) ? '🎨' : '🌐'
}

export default function Message({
  role,
  content,
  meta,
  pending,
  search,
  trace,
  metrics,
  form,
  formState,
  onFormSubmit,
  onFormCancel,
  images,
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
  if (
    !isUser && pending && !content && !thinking && !search && !trace?.length && !form
    && !images?.length
  )
    return null

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
          <div
            className={`search ${DRAWING.has(search) ? 'search--draw' : ''} ${
              search === 'searching' || search === 'drawing' ? 'search--live' : ''
            }`}
          >
            <span className="search__glyph" aria-hidden="true">{glyphFor(search)}</span>
            {describeSearch(search)}
          </div>
        )}

        {!isUser && (
          <Reasoning text={thinking} active={thinkingActive} ms={thinkingMs} />
        )}

        {images?.length > 0 && (
          <div className="drawn">
            {images.map((img, i) => (
              <figure key={img.url ?? i} className="drawn__item">
                {/* Opens full size in a new tab — the bubble is far narrower
                    than the 1536px the model draws at. */}
                <a href={img.url} target="_blank" rel="noreferrer">
                  <img
                    className="drawn__img"
                    src={img.url}
                    alt={img.revised_prompt || 'Generated image'}
                    loading="lazy"
                  />
                </a>
                {/* What the model actually asked for, which is rarely what the
                    user typed — it explains why the picture looks as it does. */}
                {img.revised_prompt && (
                  <figcaption className="drawn__prompt">
                    <Clamped text={img.revised_prompt} />
                  </figcaption>
                )}
              </figure>
            ))}
          </div>
        )}

        {/* No bubble until there is something in it. While the answer is
            still on its way the typing dots are the single indicator — an
            empty bubble here would be a second one saying the same thing. */}
        {(content || (!pending && !thinking)) && (
          <div className="msg__bubble">
            {/* The user's own text is shown verbatim (and capped, with a
                Show more toggle); only model replies are parsed as markdown. */}
            {isUser ? <Clamped text={content} /> : <Markdown>{content}</Markdown>}
            {pending && !thinkingActive && search !== 'searching' && search !== 'drawing'
              && <span className="caret" />}
          </div>
        )}

        {/* Under the reply, not above it: the model's line is "fill this in",
            and the thing being pointed at should follow the pointing. */}
        {!isUser && form && (
          <ToolForm
            spec={form}
            state={formState}
            onSubmit={onFormSubmit}
            onCancel={onFormCancel}
          />
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
