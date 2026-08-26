import { useId } from 'react'

// The app mark, same one as public/favicon.svg — inline so it takes the
// accent colour from CSS and themes with the rest of the UI.
//
// The bot is one filled rect with the eyes and smile cut out by a mask, so
// there is no tile: it sits on whatever background it is placed on.
export default function BotLogo({ size = 30 }) {
  // Several of these render at once (one per message), and duplicate ids in
  // one document make every instance use the first one's mask.
  const mask = useId()

  return (
    <svg
      className="botlogo"
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="Assistant"
    >
      <mask id={mask}>
        {/* white = keep, black = cut away */}
        <rect width="64" height="64" fill="#000" />
        <circle cx="32" cy="10.5" r="4" fill="#fff" />
        <rect x="9" y="16" width="46" height="34" rx="11" fill="#fff" />
        <circle cx="23.5" cy="30" r="5" fill="#000" />
        <circle cx="40.5" cy="30" r="5" fill="#000" />
        <path
          d="M23.5 40c2.3 2.7 5.2 4 8.5 4s6.2-1.3 8.5-4"
          fill="none"
          stroke="#000"
          strokeWidth="4"
          strokeLinecap="round"
        />
      </mask>

      <rect width="64" height="64" fill="currentColor" mask={`url(#${mask})`} />
    </svg>
  )
}
