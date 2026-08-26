// Turning the on-screen conversation into a file the user can keep.

/** Markdown export — readable, pastes cleanly into notes or a PR. */
export function toMarkdown(messages, config, stamp) {
  const lines = [
    '# Chatbot conversation',
    '',
    `- **Exported:** ${stamp.toLocaleString()}`,
    config ? `- **Provider:** ${config.provider} · ${config.model}` : null,
    config?.system_prompt ? `- **System prompt:** ${config.system_prompt}` : null,
    '',
    '---',
    '',
  ].filter(Boolean)

  for (const m of messages) {
    if (m.role === 'note') {
      lines.push(`_${m.content}_`, '')
      continue
    }
    lines.push(m.role === 'user' ? '### You' : `### Assistant${m.meta ? ` (${m.meta})` : ''}`, '')
    if (m.thinking) {
      lines.push('<details><summary>Reasoning</summary>', '', m.thinking, '', '</details>', '')
    }
    lines.push(m.content, '')
  }

  return lines.join('\n')
}

/** JSON export — the same shape the API is sent, handy for replaying a run. */
export function toJson(messages, config, stamp) {
  return JSON.stringify(
    {
      exported_at: stamp.toISOString(),
      config,
      messages: messages
        .filter((m) => m.role !== 'note')
        .map(({ role, content, meta }) => ({ role, content, model: meta })),
    },
    null,
    2,
  )
}

/** Hand the text to the browser as a file download. */
export function download(filename, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Give the browser a moment to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** chat-2026-08-25-1432 */
export function stampName(stamp) {
  const p = (n) => String(n).padStart(2, '0')
  return `chat-${stamp.getFullYear()}-${p(stamp.getMonth() + 1)}-${p(stamp.getDate())}-${p(stamp.getHours())}${p(stamp.getMinutes())}`
}
