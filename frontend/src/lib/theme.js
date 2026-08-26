// Light / dark handling.
//
// Three states, not two: "system" follows the OS, and the other two override
// it. The choice is written to <html data-theme> — styles.css keys off that
// attribute, and its absence means "follow the OS".

export const THEMES = ['system', 'light', 'dark']
const KEY = 'chatbot.theme'

export function readTheme() {
  try {
    const saved = localStorage.getItem(KEY)
    return THEMES.includes(saved) ? saved : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme) {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)

  try {
    localStorage.setItem(KEY, theme)
  } catch {
    /* private mode — the theme still applies for this session */
  }
}
