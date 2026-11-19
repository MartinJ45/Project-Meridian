import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import PartPanel from './PartPanel.jsx'

export default function DocumentsView({ selected, onSelect }) {
  const [docs, setDocs] = useState([])
  const [q, setQ] = useState('')

  useEffect(() => { api.documents().then(setDocs) }, [])

  const groups = useMemo(() => {
    const f = q.toLowerCase()
    const out = {}
    for (const d of docs) {
      if (f && !`${d.id} ${d.title} ${d.subsystem}`.toLowerCase().includes(f)) continue
      ;(out[d.subsystem] ||= []).push(d)
    }
    return out
  }, [docs, q])

  return (
    <div className="docs-layout">
      <aside className="doc-list">
        <input placeholder="Filter drawings…" value={q} onChange={(e) => setQ(e.target.value)} />
        {Object.entries(groups).map(([sub, items]) => (
          <div key={sub}>
            <h5>{sub}</h5>
            {items.map((d) => (
              <button key={d.id} className={`doc-item ${selected === d.id ? 'active' : ''}`} onClick={() => onSelect(d.id)}>
                <span>{d.id} · {d.title}</span>
                <span className="tags">
                  {d.distribution === 'degraded-only' && <em className="tag warn">degraded</em>}
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
