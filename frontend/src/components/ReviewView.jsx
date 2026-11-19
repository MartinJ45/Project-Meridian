import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function ReviewView() {
  const [items, setItems] = useState([])
  const [audit, setAudit] = useState([])
  const [notes, setNotes] = useState({})
  const [error, setError] = useState(null)

  const load = () => {
    api.corrections().then(setItems)
    api.audit().then(setAudit)
  }
  useEffect(load, [])

  async function decide(id, accept) {
    setError(null)
    try {
      await api.review(id, accept, notes[id] || '')
      load()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="review">
      <h2>Corrections review</h2>
      <p className="muted">
        Corrections proposed in chat wait here. Accepting one supersedes the old fact; the original evidence and
        this history stay visible.
      </p>
      {error && <div className="banner error">{error}</div>}
      {items.length === 0 && <p className="muted">No corrections yet. Propose one in chat, e.g. “The material for BOM row N is wrong, it should be …”.</p>}
      {items.map((c) => (
        <article key={c.id} className={`card ${c.status}`}>
          <header>
            <b>#{c.id}</b> · {c.subject_type === 'bom_row' ? `BOM row ${c.subject_id}` : c.subject_id} ·{' '}
            <code>{c.predicate}</code>
            <em className={`tag ${c.status}`}>{c.status}</em>
            <span className="muted small"> {c.created_at} via {c.proposed_via}</span>
          </header>
          <div className="diff">
            <div><span className="muted small">Current</span><div className="old">{c.old_value || '— none —'}</div></div>
            <div><span className="muted small">Proposed</span><div className="new">{c.new_value}</div></div>
          </div>
          {c.rationale && <p><span className="muted small">Rationale:</span> {c.rationale}</p>}
          <ul className="checks">
            {(c.check_report.checks || []).map((k, i) => (
              <li key={i} className={k.ok ? 'ok' : 'fail'}>{k.ok ? '✓' : '!'} {k.name}: <span className="muted">{k.detail}</span></li>
            ))}
          </ul>
          {c.status === 'pending' ? (
            <div className="decide">
              <input placeholder="Reviewer note" value={notes[c.id] || ''} onChange={(e) => setNotes({ ...notes, [c.id]: e.target.value })} />
              <button className="accept" onClick={() => decide(c.id, true)}>Accept</button>
              <button className="reject" onClick={() => decide(c.id, false)}>Reject</button>
            </div>
          ) : (
            <p className="muted small">Reviewed {c.reviewed_at}{c.reviewer_note ? ` — “${c.reviewer_note}”` : ''}</p>
          )}
        </article>
      ))}
      <h3>Audit log</h3>
      <table className="audit">
        <thead><tr><th>Time (UTC)</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
        <tbody>
          {audit.map((a) => (
            <tr key={a.id}><td>{a.ts}</td><td>{a.action}</td><td>{a.entity} {a.entity_id}</td><td><code>{JSON.stringify(a.detail)}</code></td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
