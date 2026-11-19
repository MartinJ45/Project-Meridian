import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { PlusIcon, TrashIcon } from './Icons.jsx'

// Server timestamps are UTC "YYYY-MM-DD HH:MM:SS".
const parseUtc = (s) => new Date(s.replace(' ', 'T') + 'Z')

function when(s) {
  const d = parseUtc(s)
  const mins = Math.round((Date.now() - d) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

function group(s) {
  const d = parseUtc(s)
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const diff = (today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000
  if (diff <= 0) return 'Today'
  if (diff === 1) return 'Yesterday'
  if (diff < 7) return 'Previous 7 days'
  return 'Older'
}

export default function HistoryView({ currentId, onOpen, onDeletedCurrent, onNew }) {
  const [chats, setChats] = useState(null)
  const [q, setQ] = useState('')
  const [error, setError] = useState(null)

  const load = () => api.chats().then(setChats).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const groups = useMemo(() => {
    const out = []
    for (const c of (chats || []).filter((c) => c.title.toLowerCase().includes(q.toLowerCase()))) {
      const g = group(c.updated_at)
      if (!out.length || out[out.length - 1].name !== g) out.push({ name: g, items: [] })
      out[out.length - 1].items.push(c)
    }
    return out
  }, [chats, q])

  async function remove(c) {
    if (!window.confirm(`Delete the chat "${c.title}"? This can't be undone.`)) return
    try {
      await api.deleteChat(c.id)
      if (c.id === currentId) onDeletedCurrent()
      load()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="history">
      <div className="history-inner">
        <header className="history-head">
          <h2>Past chats</h2>
          <button className="new-chat" onClick={onNew}><PlusIcon width={18} height={18} /> New chat</button>
        </header>
        <input className="history-search" placeholder="Search chats…" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Search chats" />
        {error && <div className="banner error">{error}</div>}
        {chats === null && !error && <p className="muted">Loading…</p>}
        {chats?.length === 0 && <p className="muted">No chats yet. Questions you ask are saved here automatically.</p>}
        {chats?.length > 0 && groups.length === 0 && <p className="muted">No chats match “{q}”.</p>}
        {groups.map((g) => (
          <section key={g.name}>
            <h5>{g.name}</h5>
            <ul className="history-list">
              {g.items.map((c) => (
                <li key={c.id} className={c.id === currentId ? 'current' : ''}>
                  <button className="history-item" onClick={() => onOpen(c.id)}>
                    <span className="history-title">{c.title}</span>
                    <span className="muted small">
                      {Math.ceil(c.message_count / 2)} question{c.message_count > 2 ? 's' : ''} · {when(c.updated_at)}
                      {c.id === currentId && ' · open'}
                    </span>
                  </button>
                  <button className="icon-btn" title="Delete chat" aria-label={`Delete chat ${c.title}`} onClick={() => remove(c)}>
                    <TrashIcon />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
