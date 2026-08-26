import { useMemo, useState } from 'react'
import { toJsxRuntime } from 'hast-util-to-jsx-runtime'
import { Fragment, jsx, jsxs } from 'react/jsx-runtime'
import { highlight } from '../lib/highlight.js'
import { copyText } from '../lib/clipboard.js'

/** A fenced code block with its language label and a copy button. */
export default function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false)

  // Highlighting produces a hast tree; render it as real React elements
  // rather than injecting HTML into the page.
  const rendered = useMemo(() => {
    const tree = highlight(code, language)
    return tree ? toJsxRuntime(tree, { Fragment, jsx, jsxs }) : code
  }, [code, language])

  async function copy() {
    await copyText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1400)
  }

  return (
    <div className="code">
      <div className="code__bar">
        <span className="code__lang">{language || 'text'}</span>
        <button className="code__copy" onClick={copy}>
          {copied ? '\u2713 Copied' : 'Copy'}
        </button>
      </div>
      <pre className="code__body">
        <code className="hljs">{rendered}</code>
      </pre>
    </div>
  )
}
