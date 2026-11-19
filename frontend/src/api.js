async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  documents: () => request('/api/documents'),
  document: (id) => request(`/api/documents/${id}`),
  bomRow: (i) => request(`/api/bom/${i}`),
  chat: (messages) => request('/api/chat', { method: 'POST', body: JSON.stringify({ messages }) }),
  corrections: (status) => request(`/api/corrections${status ? `?status=${status}` : ''}`),
  review: (id, accept, note) =>
    request(`/api/corrections/${id}/${accept ? 'accept' : 'reject'}`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  audit: () => request('/api/audit'),
}
