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

export const api = {
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
