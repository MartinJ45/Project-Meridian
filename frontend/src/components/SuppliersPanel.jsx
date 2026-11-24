import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Potential suppliers for a drawn part: profile from evidence, recorded BOM supplier, and web-search leads.
export default function SuppliersPanel({ docId }) {
  const [info, setInfo] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { setInfo(null); api.suppliers(docId).then(setInfo).catch((e) => setError(e.message)) }, [docId])

  async function runSearch() {
    setBusy(true)
    setError(null)
    try {
      const search = await api.supplierSearch(docId)
      setInfo({ ...info, search })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !info) return <div className="evidence"><p className="bad-text small">{error}</p></div>
  if (!info) return <div className="evidence muted">Loading…</div>
  const { profile: p, internal, search } = info
  return (
    <div className="evidence suppliers">
      <section>
        <h4>What the part needs <span className="muted small">(from the extracted drawing and BOM)</span></h4>
        <table>
          <tbody>
            <tr><th>Material</th><td>
              {p.material.drawing || '—'} <span className="muted small">{p.material.drawing_ref ? `[${p.material.drawing_ref}]` : ''}</span>
              {p.material.bom.length > 0 && <div className="small">BOM: {p.material.bom.join(', ')}</div>}
            </td></tr>
            <tr><th>Processes</th><td>
              <ul className="plain">{p.processes.map((x) => (
                <li key={x.process}><b>{x.process}</b><div className="muted small">{x.evidence}</div></li>
              ))}</ul>
            </td></tr>
            <tr><th>Size</th><td>{p.largest_dimension_mm ? `largest dimension ≈ ${p.largest_dimension_mm} mm` : '—'}</td></tr>
            <tr><th>Quantity</th><td>
              {p.quantity.drawing ? `sheet: ${p.quantity.drawing}` : 'sheet: not stated'}
              {p.quantity.bom.length > 0 && ` · BOM: ${p.quantity.bom.join(', ')}`}
            </td></tr>
          </tbody>
        </table>
      </section>
      <section>
        <h4>Recorded in the BOM <em className="tag">pinned snapshot</em></h4>
        {internal.recorded.length === 0 && <p className="muted small">No BOM row is linked to this drawing.</p>}
        {internal.recorded.map((r) => (
          <p key={r.row} className="small">
            Row {r.row} {r.name}: <b>{r.supplier || 'no supplier recorded'}</b>
            {r.order && ` · order ${r.order}`}{r.cost_dkk && ` · DKK ${r.cost_dkk}`}
          </p>
        ))}
        {internal.same_material_in_bom.length > 0 && (
          <p className="small muted">
            Other BOM suppliers of the same material: {internal.same_material_in_bom.slice(0, 5)
              .map((s) => `${s.supplier} (${s.count})`).join(', ')}
          </p>
        )}
      </section>
      <section>
        <h4>Potential suppliers <em className="tag warn">web search · leads</em></h4>
        {!search && <p className="small muted">No search run yet for this part.</p>}
        {search && (
          <>
            <p className="small muted">
              Retrieved {search.retrieved_at.replace('T', ' ').slice(0, 16)} UTC · {search.region} · searched for “{search.profile_used.processes}” in {search.profile_used.material}
            </p>
            {search.suggestions.length === 0 && <p className="small">The search returned no usable suggestions.</p>}
            {search.suggestions.map((s, i) => (
              <div key={i} className="supplier-card">
                <div><b>{s.name}</b> <span className="muted small">{s.location}</span></div>
                {s.website && <a className="small" href={s.website} target="_blank" rel="noreferrer">{s.website}</a>}
                <div className="small">{s.basis}</div>
                <div className="ev-meta">
                  {(s.matches || []).map((m) => <em key={m} className="tag">{m}</em>)}
                  {s.in_search_results
                    ? <span className="check-chip ok">✓ website in search results</span>
                    : <span className="check-chip fail">! website not seen in search results</span>}
                </div>
              </div>
            ))}
            {search.sources.length > 0 && (
              <details className="small">
                <summary>{search.sources.length} search sources</summary>
                <ul>{search.sources.map((s, i) => <li key={i}><a href={s.uri} target="_blank" rel="noreferrer">{s.title}</a></li>)}</ul>
              </details>
            )}
          </>
        )}
        <p className="small muted">{info.caveat}</p>
        {info.search_available
          ? <button className="ghost" onClick={runSearch} disabled={busy}>{busy ? 'Searching the web… (10–40 s)' : search ? 'Search again' : 'Search for potential suppliers'}</button>
          : <p className="small muted">Web search needs an API key (offline mode).</p>}
        {error && <p className="small bad-text">{error}</p>}
      </section>
    </div>
  )
}
