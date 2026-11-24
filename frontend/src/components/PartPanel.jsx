import { useEffect, useState } from 'react'
import { api } from '../api.js'
import PdfViewer from './PdfViewer.jsx'
import ModelViewer from './ModelViewer.jsx'
import SuppliersPanel from './SuppliersPanel.jsx'

const CHECK = {
  text_layer_match: { label: 'matches PDF text', ok: true },
  repeat_read_agrees: { label: 'two readings agree', ok: true },
  repeat_read_disagrees: { label: 'readings disagree', ok: false },
  not_in_text_layer: { label: 'not in PDF text', ok: false },
}

const LINK_TAG = { confirmed: 'ok', probable: 'warn', none: '' }

const VERDICT = {
  agree: { label: 'agree', tag: 'ok' },
  drawing_more_specific: { label: 'agree · drawing more specific', tag: 'ok' },
  conflict: { label: 'conflict', tag: 'bad' },
  missing_on_drawing: { label: 'not on drawing', tag: 'warn' },
  missing_in_bom: { label: 'not in BOM', tag: 'warn' },
}

const FIELD_LABEL = {
  title: 'Title', material: 'Material', weight_g: 'Weight [g]', scale: 'Scale', sheet: 'Sheet', date: 'Date',
  company: 'Company', finish: 'Finish', general_tolerance: 'General tolerance', paper_size: 'Paper size', note: 'Note',
}

// One drawing: 2D sheet, 3D reconstruction (if built) and the extracted evidence.
export default function PartPanel({ docId, initialTab = '2d', onClose, onExpand }) {
  const [doc, setDoc] = useState(null)
  const [tab, setTab] = useState(initialTab)
  const [highlight, setHighlight] = useState(null) // { box_2d, page, label }

  useEffect(() => {
    setDoc(null)
    setHighlight(null)
    api.document(docId).then(setDoc)
  }, [docId])
  useEffect(() => { setTab(initialTab) }, [docId, initialTab])

  if (!doc) return <div className="panel loading">Loading {docId}…</div>
  const effectiveTab = tab === '3d' && !doc.model ? '2d' : tab
  const showOnSheet = (h) => { setHighlight(h); setTab('2d') }

  return (
    <div className="panel">
      <header className="panel-head">
        <div>
          <div className="title">
            {doc.id} · {doc.title}
            {doc.distribution === 'degraded-only'
              ? <em className="tag warn">degraded scan</em>
              : <em className="tag">clean</em>}
            {doc.model && <em className="tag recon">3D reconstruction</em>}
          </div>
          <div className="muted small">{doc.subsystem} · {doc.role} · {doc.source_path}</div>
        </div>
        <div className="actions">
          {onExpand && <button className="ghost" onClick={onExpand}>Open in Drawings</button>}
          {onClose && <button className="ghost" onClick={onClose}>✕</button>}
        </div>
      </header>
      <div className="tabs">
        <button className={effectiveTab === '2d' ? 'active' : ''} onClick={() => setTab('2d')}>2D drawing</button>
        <button className={effectiveTab === '3d' ? 'active' : ''} onClick={() => setTab('3d')} disabled={!doc.model}
          title={doc.model ? '' : 'No reconstruction built for this drawing'}>3D model</button>
        <button className={effectiveTab === 'detail' ? 'active' : ''} onClick={() => setTab('detail')}>Evidence</button>
        <button className={effectiveTab === 'suppliers' ? 'active' : ''} onClick={() => setTab('suppliers')}>Suppliers</button>
      </div>
      <div className="panel-body">
        {effectiveTab === '2d' && (
          <PdfViewer url={doc.file_url} highlight={highlight} onClearHighlight={() => setHighlight(null)} />
        )}
        {effectiveTab === '3d' && <ModelViewer model={doc.model} />}
        {effectiveTab === 'detail' && <Evidence doc={doc} onShow={showOnSheet} />}
        {effectiveTab === 'suppliers' && <SuppliersPanel docId={doc.id} />}
      </div>
    </div>
  )
}

function Legibility({ value }) {
  if (!value || value === 'clear') return null
  return <em className={`tag ${value === 'illegible' ? 'bad' : 'warn'}`}>{value}</em>
}

function Check({ value }) {
  const c = CHECK[value]
  if (!c) return null
  return <span className={`check-chip ${c.ok ? 'ok' : 'fail'}`}>{c.ok ? '✓' : '!'} {c.label}</span>
}

// Propose a link change (or confirm a probable link). It goes to the Review page like any correction.
function LinkReview({ doc }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState('')
  const [why, setWhy] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmed, setConfirmed] = useState(false) // confirmation already sent for this drawing
  useEffect(() => { setOpen(false); setRows(''); setWhy(''); setMsg(null); setBusy(false); setConfirmed(false) }, [doc.id])
  const current = doc.bom_links.filter((l) => l.method === 'curated' || l.method === 'correction').map((l) => l.row_index)
  const submit = async (value, rationale, isConfirm = false) => {
    if (busy) return
    setBusy(true)
    try {
      const c = await api.propose({ subject_type: 'document', subject_id: doc.id, predicate: 'bom_link', new_value: value, rationale })
      const flagged = c.check_report.checks.filter((k) => !k.ok).map((k) => k.name)
      setMsg(c.duplicate
        ? `This change is already waiting for review as correction #${c.id}.`
        : `Sent for review as correction #${c.id}${flagged.length ? ` — checks flagged: ${flagged.join(', ')}` : ''}.`)
      setOpen(false)
      setRows('')
      setWhy('')
      if (isConfirm) setConfirmed(true)
    } catch (e) {
      setMsg(`Could not propose: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="link-review">
      {doc.link_decision?.status === 'probable' && current.length > 0 && !confirmed && (
        <button className="ghost small" disabled={busy}
          onClick={() => submit(current.join(','), 'Link checked against the drawing.', true)}>
          Confirm this link
        </button>
      )}
      <button className="ghost small" disabled={busy} onClick={() => setOpen(!open)}>Propose a different link…</button>
      {open && (
        <form className="link-form" onSubmit={(e) => { e.preventDefault(); if (rows.trim()) submit(rows.trim(), why) }}>
          <input placeholder="BOM row number(s), e.g. 81 or 91,93 — or none" value={rows} onChange={(e) => setRows(e.target.value)} />
          <input placeholder="Why (evidence)" value={why} onChange={(e) => setWhy(e.target.value)} />
          <button type="submit" disabled={busy || !rows.trim()}>{busy ? 'Sending…' : 'Send for review'}</button>
        </form>
      )}
      {msg && <p className="small muted">{msg}</p>}
    </div>
  )
}

// Small line under a value: feature / legibility / check badges and the "show on sheet" link.
function Meta({ children }) {
  return <div className="ev-meta">{children}</div>
}

function ShowButton({ box, page, label, onShow }) {
  if (!box || box.length !== 4) return null
  return (
    <button className="link-btn" onClick={() => onShow({ box_2d: box, page, label })} title="Highlight on the sheet">
      show
    </button>
  )
}

function Evidence({ doc, onShow }) {
  const tb = doc.facts.filter((f) => f.source_type === 'drawing')
  const dims = doc.annotations.filter((a) => a.kind === 'dimension')
  const callouts = doc.annotations.filter((a) => a.kind === 'callout')
  const quality = doc.quality[0]
  return (
    <div className="evidence">
      <section>
        <h4>
          BOM link{' '}
          {doc.link_decision
            ? <em className={`tag ${LINK_TAG[doc.link_decision.status]}`}>{doc.link_decision.status}</em>
            : <em className="tag warn">not reviewed</em>}
        </h4>
        {doc.link_decision && <p className="small">{doc.link_decision.rationale}</p>}
        <LinkReview doc={doc} />
        {!doc.link_decision && <p className="muted small">Only unconfirmed filename matches below.</p>}
        {doc.bom_links.length === 0 && <p className="muted small">No BOM row is linked to this drawing.</p>}
        {doc.bom_links.length > 0 && (
          <table>
            <tbody>
              {doc.bom_links.map((l) => (
                <tr key={`${l.row_index}-${l.method}`}>
                  <th>Row {l.row_index}</th>
                  <td>
                    <div>{l.name}</div>
                    <Meta>
                      <span className="muted">{l.part_family}</span>
                      <span className="muted">material: {l.material || '—'}</span>
                      {l.method !== 'curated' && (
                        <span className="muted">filename match {Math.round(l.score)} (unconfirmed)</span>
                      )}
                    </Meta>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {doc.consistency?.length > 0 && (
        <section>
          <h4>Drawing vs BOM</h4>
          <table>
            <tbody>
              {doc.consistency.map((c) => (
                <tr key={c.id}>
                  <th>{c.field === 'quantity' ? 'Quantity' : 'Material'}<div className="muted small">row {c.row_index}</div></th>
                  <td>
                    <div className="small"><span className="muted">Drawing:</span> {c.drawing_value || '—'}</div>
                    <div className="small"><span className="muted">BOM:</span> {c.bom_value || '—'}
                      {c.bom_ref?.startsWith('correction') && <span className="muted"> ({c.bom_ref})</span>}</div>
                    <Meta>
                      <em className={`tag ${VERDICT[c.verdict]?.tag || ''}`}>{VERDICT[c.verdict]?.label || c.verdict}</em>
                      <span className="muted">{c.detail}</span>
                    </Meta>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {quality && (
        <section>
          <h4>Sheet reading</h4>
          <p className="small">
            Legibility: <b>{quality.legibility.replace('_', ' ')}</b>
            {quality.issues && <span className="muted"> — {quality.issues}</span>}
          </p>
        </section>
      )}
      {doc.derivation && (
        <section>
          <h4>Degradation notice</h4>
          <p className="muted small">{doc.derivation.modification_notice}</p>
        </section>
      )}
      <section>
        <h4>Title block</h4>
        {tb.length === 0 && <p className="muted">No fields extracted from this drawing yet.</p>}
        {tb.length > 0 && (
          <table>
            <tbody>
              {tb.map((f) => {
                const ev = f.evidence || {}
                return (
                  <tr key={f.id} className={f.status}>
                    <th>{FIELD_LABEL[f.predicate] || f.predicate}</th>
                    <td>
                      <div className="pre">
                        {f.value ?? <span className="muted">{ev.empty_on_sheet ? 'empty on sheet' : 'illegible'}</span>}
                      </div>
                      {ev.alternative_reading != null && (
                        <div className="muted small">other reading: “{ev.alternative_reading}”</div>
                      )}
                      <Meta>
                        <Legibility value={ev.legibility} />
                        <Check value={ev.check} />
                        <ShowButton box={ev.box_2d} page={ev.page} label={FIELD_LABEL[f.predicate]} onShow={onShow} />
                      </Meta>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
      {[['Dimensions', dims], ['Callouts', callouts]].map(([title, items]) => items.length > 0 && (
        <section key={title}>
          <h4>{title} <span className="muted small">({items.length}, as written on the sheet)</span></h4>
          <table>
            <tbody>
              {items.map((a, i) => (
                <tr key={i}>
                  <td>
                    <div className="pre">{a.text || <span className="muted">illegible</span>}</div>
                    <Meta>
                      {a.feature && a.feature !== 'unknown' && <span className="muted">{a.feature}</span>}
                      <Legibility value={a.legibility} />
                      <ShowButton box={a.box_2d} page={a.page} label={a.text} onShow={onShow} />
                    </Meta>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      <details>
        <summary className="small">Raw PDF text layer</summary>
        {doc.pages_text.map((p) => (
          <div key={p.page}>
            <div className="muted small">page {p.page} · {p.has_text_layer ? 'text layer' : 'no text layer (raster scan)'}</div>
            {p.text && <pre className="text">{p.text}</pre>}
          </div>
        ))}
      </details>
      <section>
        <h4>Provenance</h4>
        <p className="small"><a href={doc.source_url} target="_blank" rel="noreferrer">{doc.source_url}</a></p>
        <p className="muted small">sha256 {doc.sha256}</p>
      </section>
    </div>
  )
}
