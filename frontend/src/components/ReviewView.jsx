import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function ReviewView({ onChanged }) {
  const [items, setItems] = useState([])
  const [audit, setAudit] = useState([])
  const [notes, setNotes] = useState({})
  const [error, setError] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [deciding, setDeciding] = useState(null) // id being accepted/rejected

  const load = () => {
    api.corrections().then(setItems)
    api.audit().then(setAudit)
    api.metrics().then(setMetrics).catch(() => {})
  }
  useEffect(load, [])

  async function decide(id, accept) {
    if (deciding) return
    setDeciding(id)
    setError(null)
    try {
      await api.review(id, accept, notes[id] || '')
      load()
      onChanged?.() // refresh the pending-corrections badge in the rail
    } catch (e) {
      setError(e.message)
    } finally {
      setDeciding(null)
    }
  }

  return (
    <div className="review">
      <h2>Review</h2>
      <p className="muted">
        Corrections proposed in chat, from the Evidence tab, or when a new drawing is added wait here. Accepting one
        supersedes the old fact or link; the original evidence and this history stay visible.
      </p>
      {metrics && <Health metrics={metrics} />}
      <h3>Corrections</h3>
      {error && <div className="banner error">{error}</div>}
      {items.length === 0 && <p className="muted">No corrections yet. Propose one in chat, e.g. “The material for BOM row N is wrong, it should be …”.</p>}
      {items.map((c) => (
        <article key={c.id} className={`card ${c.status}`}>
          <header>
            <b>#{c.id}</b> · {c.subject_type === 'bom_row' ? `BOM row ${c.subject_id}` : c.subject_id} ·{' '}
            <code>{c.predicate === 'bom_link' ? 'BOM link (row numbers)' : c.predicate}</code>
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
              <button className="accept" disabled={!!deciding} onClick={() => decide(c.id, true)}>Accept</button>
              <button className="reject" disabled={!!deciding} onClick={() => decide(c.id, false)}>Reject</button>
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

function Health({ metrics }) {
  const n = metrics.now
  const cards = [
    ['Links confirmed', n.links.confirmed, `${n.links.probable} probable · ${n.links.none} no BOM row`],
    ['Drawing/BOM conflicts', n.consistency.conflicts, `${n.consistency.missing} values missing on one side`],
    ['Drawing fields verified', `${n.extraction.independently_verified}/${n.extraction.drawing_fields}`, 'by PDF text layer or a second reading'],
    ['Corrections accepted', n.corrections.accepted,
      Object.entries(n.corrections.accepted_by_type).map(([k, v]) => `${v} ${k}`).join(' · ') || `${n.corrections.pending} pending`],
    ['Drawings', n.drawings, n.uploaded_drawings ? `${n.uploaded_drawings} added in the app` : 'from the dataset'],
  ]
  return (
    <section className="health">
      <h3>Knowledge health</h3>
      <div className="health-cards">
        {cards.map(([label, value, sub]) => (
          <div key={label} className="health-card">
            <div className="muted small">{label}</div>
            <div className="health-value">{value}</div>
            <div className="muted small">{sub}</div>
          </div>
        ))}
      </div>
      {metrics.history.length > 0 && (
        <>
          <h4>After each reviewed change</h4>
          <table className="audit">
            <thead><tr><th>Time (UTC)</th><th>Event</th><th>Confirmed links</th><th>Probable</th><th>Conflicts</th><th>Missing</th><th>Pending</th></tr></thead>
            <tbody>
              {metrics.history.slice().reverse().map((h, i) => (
                <tr key={i}>
                  <td>{h.ts.replace('T', ' ').slice(0, 19)}</td><td>{h.event}</td><td>{h.links.confirmed}</td>
                  <td>{h.links.probable}</td><td>{h.consistency.conflicts}</td><td>{h.consistency.missing}</td>
                  <td>{h.corrections.pending}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {metrics.eval_runs.length > 0 && (
        <>
          <h4>Evaluation runs <span className="muted small">(python -m app.evaluate)</span></h4>
          <table className="audit">
            <thead><tr><th>Run (UTC)</th><th>Passed</th><th>Median latency</th><th>Correction before/after</th></tr></thead>
            <tbody>
              {metrics.eval_runs.slice().reverse().map((r) => (
                <tr key={r.started}>
                  <td>{r.started.replace('T', ' ').slice(0, 19)}</td>
                  <td>{r.passed}/{r.total} ({Math.round((100 * r.passed) / r.total)}%)</td>
                  <td>{r.median_latency_s} s</td>
                  <td>{r.correction_demo_ok == null ? '—' : r.correction_demo_ok ? 'all checks passed' : 'failed'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  )
}
