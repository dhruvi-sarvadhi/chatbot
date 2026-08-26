// Syntax highlighting for fenced code blocks.
//
// highlight.js ships ~190 languages and rehype-highlight pulls in ~35 of them
// unconditionally, which tripled the app's JavaScript. Registering only what a
// chatbot realistically emits keeps the bundle small.

import { createLowlight } from 'lowlight'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

const lowlight = createLowlight({
  bash, css, javascript, json, markdown, python, sql, typescript, xml, yaml,
})

// Common aliases the model writes in its fences.
const ALIASES = {
  js: 'javascript', jsx: 'javascript', mjs: 'javascript',
  ts: 'typescript', tsx: 'typescript',
  py: 'python', sh: 'bash', shell: 'bash', zsh: 'bash', console: 'bash',
  html: 'xml', svg: 'xml', yml: 'yaml', md: 'markdown', curl: 'bash',
}

/** Returns a hast tree, or null when the language is unknown. */
export function highlight(code, language) {
  const name = ALIASES[language] || language
  if (!name || !lowlight.registered(name)) return null
  try {
    return lowlight.highlight(name, code)
  } catch {
    return null
  }
}
