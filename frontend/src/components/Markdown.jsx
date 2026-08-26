import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import CodeBlock from './CodeBlock.jsx'

/**
 * Renders a model reply as formatted markdown instead of raw text:
 * headings, bold/italic, ordered + nested lists, tables, blockquotes,
 * links, inline code and fenced code blocks with syntax highlighting.
 *
 * Raw HTML in the model's output is NOT rendered (react-markdown ignores it
 * unless you add rehype-raw), so a reply can't inject markup into the page.
 */
export default function Markdown({ children }) {
  const text = normalise(children)

  return (
    <div className="md">
      <ReactMarkdown
        // gfm: tables, strikethrough, task lists, autolinks
        // breaks: a single newline becomes a line break, like chat apps do
        // (code blocks are highlighted inside CodeBlock, not by a rehype plugin)
        remarkPlugins={[remarkGfm, remarkBreaks]}
        components={{
          // Fenced blocks get the copy button; inline code stays inline.
          pre: ({ children }) => <>{children}</>,
          code: ({ inline, className, children, ...props }) => {
            const value = String(children ?? '').replace(/\n$/, '')
            const isBlock = !inline && (className?.includes('language-') || value.includes('\n'))

            if (!isBlock) {
              return <code className="md__inline" {...props}>{children}</code>
            }
            return <CodeBlock language={/language-(\w+)/.exec(className || '')?.[1]} code={value} />
          },
          // Wide tables scroll inside the bubble instead of stretching it.
          table: ({ children }) => (
            <div className="md__tablewrap">
              <table>{children}</table>
            </div>
          ),
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

/**
 * If the whole reply is a bare JSON object/array with no code fence, wrap it
 * in one so it renders pretty-printed and highlighted rather than as a wall
 * of text on a single line.
 */
function normalise(input) {
  const text = String(input ?? '')
  const trimmed = text.trim()
  if (!/^[[{]/.test(trimmed) || !/[\]}]$/.test(trimmed)) return text

  try {
    const parsed = JSON.parse(trimmed)
    if (parsed && typeof parsed === 'object') {
      return '```json\n' + JSON.stringify(parsed, null, 2) + '\n```'
    }
  } catch {
    /* not JSON — render as written */
  }
  return text
}
