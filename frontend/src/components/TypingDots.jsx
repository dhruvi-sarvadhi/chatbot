import BotLogo from './BotLogo.jsx'

// Shown while we are waiting for the first token to arrive.
export default function TypingDots() {
  return (
    <div className="msg msg--bot">
      <div className="msg__avatar msg__avatar--logo">
        <BotLogo />
      </div>
      <div className="msg__bubble msg__bubble--typing">
        <span /><span /><span />
      </div>
    </div>
  )
}
