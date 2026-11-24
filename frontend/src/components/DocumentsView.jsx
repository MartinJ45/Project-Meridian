import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import PartPanel from './PartPanel.jsx'
import { PlusIcon } from './Icons.jsx'

export default function DocumentsView({ selected, onSelect }) {
  const [docs, setDocs] = useState([])
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState(false)

  const load = () => api.documents().then(setDocs)
  useEffect(() => { load() }, [])

  const groups = useMemo(() => {
    const f = q.toLowerCase()
    const out = {}
    for (const d of docs) {
      if (f && !`${d.id} ${d.title} ${d.subsystem}`.toLowerCase().includes(f)) continue
      ;(out[d.subsystem] ||= []).push(d)
    }
    return out
  }, [docs, q])
  const subsystems = useMemo(() => [...new Set(docs.map((d) => d.subsystem))], [docs])

  return (
    <div className="docs-layout">
      <aside className="doc-list">
        <div className="doc-list-head">
          <input placeholder="Filter drawings…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="icon-btn boxed" title="Add a drawing" aria-label="Add a drawing" onClick={() => setAdding(!adding)}>
            <PlusIcon width={18} height={18} />
          </button>
        </div>
        {adding && (
          <AddDrawing subsystems={subsystems} onDone={(id) => { load(); onSelect(id) }} onClose={() => setAdding(false)} />
        )}
        {Object.entries(groups).map(([sub, items]) => (
          <div key={sub}>
            <h5>{sub}</h5>
            {items.map((d) => (
              <button key={d.id} className={`doc-item ${selected === d.id ? 'active' : ''}`} onClick={() => onSelect(d.id)}>
                <span>{d.id} · {d.title}</span>
                <span className="tags">
                  {d.distribution === 'degraded-only' && <em className="tag warn">degraded</em>}
                  {d.distribution === 'uploaded' && <em className="tag">uploaded</em>}
                  {d.has_model && <em className="tag recon">3D</em>}
                </span>
              </button>
            ))}
          </div>
        ))}
      </aside>
      <section className="doc-main">
        {selected ? <PartPanel docId={selected} /> : <div className="empty muted">Select a drawing</div>}
      </section>
    </div>
  )
}

// Upload a new drawing PDF; the server extracts it and proposes a BOM link for review.
function AddDrawing({ subsystems, onDone, onClose }) {
  const [file, setFile] = useState(null)
  const [subsystem, setSubsystem] = useState(subsystems[0] || 'Box')
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)

  async function submit(e) {
    e.preventDefault()
    if (!file) return
    setError(null)
    try {
      const item = await api.upload(file, subsystem)
      setStatus({ id: item.id, state: 'queued', steps: [] })
      const poll = setInterval(async () => {
        const s = await api.uploadStatus(item.id).catch(() => null)
        if (!s) return
        setStatus(s)
        if (s.state === 'done' || s.state === 'failed') {
          clearInterval(poll)
          if (s.state === 'done') onDone(item.id)
        }
      }, 1500)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="add-drawing" onSubmit={submit}>
      <div className="small"><b>Add a drawing</b> <span className="muted">— PDF; read, linked and sent for review</span></div>
      <input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} aria-label="Drawing PDF" />
      <label className="small">Subsystem{' '}
        <select value={subsystem} onChange={(e) => setSubsystem(e.target.value)}>
          {subsystems.map((s) => <option key={s}>{s}</option>)}
          <option>Unassigned</option>
        </select>
      </label>
      <div className="row-btns">
        <button type="submit" disabled={!file || (status && status.state !== 'done' && status.state !== 'failed')}>Upload</button>
        <button type="button" className="ghost" onClick={onClose}>Close</button>
      </div>
      {error && <p className="small bad-text">{error}</p>}
      {status && (
        <div className="small">
          <div><b>{status.id}</b>: {status.state}{status.state === 'processing' || status.state === 'queued' ? '…' : ''}</div>
          <ul>{status.steps.map((s, i) => <li key={i} className="muted">{s}</li>)}</ul>
        </div>
      )}
    </form>
  )
}
