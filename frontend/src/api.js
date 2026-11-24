// FastAPI sends `detail` as a string, or as a list of validation errors ({loc, msg}).
function errorText(detail) {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const text = detail.map((d) => `${(d.loc || []).filter((p) => p !== 'body').join('.')}: ${d.msg}`).join('; ')
    return `The server rejected the request (${text}). If the server was started before an update, restart it.`
  }
  return JSON.stringify(detail)
}

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body.detail) || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

// Streams a chat turn: calls onEvent for each event (start, delta, reset) and resolves with the final
// "done" event (same fields as /api/chat).
async function chatStream(message, chatId, onEvent) {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, chat_id: chatId || null }),
  })
  if (res.status === 404 || res.status === 405) {
    // Server started before streaming existed: answer in one piece instead.
    const whole = await request('/api/chat', { method: 'POST', body: JSON.stringify({ message, chat_id: chatId || null }) })
    return { type: 'done', ...whole }
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(errorText(body.detail) || `${res.status} ${res.statusText}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done = null
  const handle = (line) => {
    if (!line.trim()) return
    const event = JSON.parse(line)
    if (event.type === 'error') throw new Error(event.message)
    if (event.type === 'done') done = event
    else onEvent?.(event)
  }
  for (;;) {
    const { value, done: finished } = await reader.read()
    if (finished) break
    buffer += decoder.decode(value, { stream: true })
    let nl
    while ((nl = buffer.indexOf('\n')) >= 0) {
      handle(buffer.slice(0, nl))
      buffer = buffer.slice(nl + 1)
    }
  }
  handle(buffer + decoder.decode())
  if (!done) throw new Error('The answer was cut off. Please try again.')
  return done
}

export const api = {
  chatStream,
  health: () => request('/api/health'),
  documents: () => request('/api/documents'),
  document: (id) => request(`/api/documents/${id}`),
  bomRow: (i) => request(`/api/bom/${i}`),
  chat: (message, chatId) =>
    request('/api/chat', { method: 'POST', body: JSON.stringify({ message, chat_id: chatId || null }) }),
  chats: () => request('/api/chats'),
  graph: () => request('/api/graph'),
  metrics: () => request('/api/metrics'),
  suppliers: (id) => request(`/api/suppliers/${id}`),
  supplierSearch: (id) => request(`/api/suppliers/${id}/search`, { method: 'POST' }),
  getChat: (id) => request(`/api/chats/${encodeURIComponent(id)}`),
  deleteChat: (id) => request(`/api/chats/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  upload: async (file, subsystem) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('subsystem', subsystem)
    const res = await fetch('/api/documents/upload', { method: 'POST', body: fd })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(errorText(body.detail) || `${res.status} ${res.statusText}`)
    return body
  },
  uploadStatus: (id) => request(`/api/uploads/${id}`),
  propose: (p) => request('/api/corrections', { method: 'POST', body: JSON.stringify(p) }),
  corrections: (status) => request(`/api/corrections${status ? `?status=${status}` : ''}`),
  review: (id, accept, note) =>
    request(`/api/corrections/${id}/${accept ? 'accept' : 'reject'}`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  audit: () => request('/api/audit'),
}
