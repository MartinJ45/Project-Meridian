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
  getChat: (id) => request(`/api/chats/${encodeURIComponent(id)}`),
  deleteChat: (id) => request(`/api/chats/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  corrections: (status) => request(`/api/corrections${status ? `?status=${status}` : ''}`),
  review: (id, accept, note) =>
    request(`/api/corrections/${id}/${accept ? 'accept' : 'reject'}`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  audit: () => request('/api/audit'),
}
