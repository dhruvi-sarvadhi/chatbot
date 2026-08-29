// Turning a browser File into something an LLM API accepts.
//
// Three routes, chosen by type, because they cost very different amounts:
//
//   image     → base64, sent as an image block. The model looks at it.
//   document  → base64 PDF. The provider extracts the pages for us.
//   text      → decoded here and pasted straight in. No upload, no
//               extraction, no per-page cost — always prefer this when the
//               file is already text.

// base64 is about a third larger than the file, and the whole conversation
// is re-sent on every turn, so this stays deliberately modest.
export const MAX_FILE_BYTES = 4 * 1024 * 1024
export const MAX_FILES = 5

const TEXT_EXTENSIONS = [
  '.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.yaml', '.yml',
  '.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.sql', '.sh',
  '.java', '.go', '.rb', '.rs', '.c', '.h', '.cpp', '.toml', '.ini', '.env',
]

export const ACCEPT = ['image/*', 'application/pdf', ...TEXT_EXTENSIONS].join(',')

function kindOf(file) {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type === 'application/pdf') return 'document'
  const name = file.name.toLowerCase()
  if (file.type.startsWith('text/') || TEXT_EXTENSIONS.some((e) => name.endsWith(e))) {
    return 'text'
  }
  return null
}

const readAs = (file, how) =>
  new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onerror = () => reject(new Error(`Could not read ${file.name}`))
    r.onload = () => resolve(r.result)
    how === 'text' ? r.readAsText(file) : r.readAsDataURL(file)
  })

/**
 * One File → one attachment object, or an Error explaining why not.
 * Rejecting with a readable reason beats silently dropping the file.
 */
export async function toAttachment(file) {
  const kind = kindOf(file)
  if (!kind) {
    throw new Error(`${file.name}: images, PDFs and text files only`)
  }
  if (file.size > MAX_FILE_BYTES) {
    const mb = (file.size / 1024 / 1024).toFixed(1)
    throw new Error(`${file.name} is ${mb}MB — the limit is ${MAX_FILE_BYTES / 1024 / 1024}MB`)
  }

  if (kind === 'text') {
    return {
      kind,
      name: file.name,
      media_type: file.type || 'text/plain',
      data: await readAs(file, 'text'),
    }
  }

  const url = await readAs(file, 'dataurl')
  return {
    kind,
    name: file.name,
    media_type: file.type,
    // Strip the "data:image/png;base64," prefix — the backend rebuilds
    // whichever wrapper its provider wants.
    data: String(url).split(',')[1] ?? '',
    // Kept only so the composer can show a thumbnail; never sent.
    preview: kind === 'image' ? String(url) : null,
  }
}

/** Strip UI-only fields before the attachment goes over the wire. */
export const forWire = ({ kind, name, media_type, data }) => ({ kind, name, media_type, data })

export function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
