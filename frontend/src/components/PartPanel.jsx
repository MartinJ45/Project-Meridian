import { useEffect, useState } from 'react'
import { api } from '../api.js'
import PdfViewer from './PdfViewer.jsx'
import ModelViewer from './ModelViewer.jsx'

// One drawing: 2D sheet, 3D reconstruction (if built) and the extracted evidence.
export default function PartPanel({ docId, initialTab = '2d', onClose, onExpand }) {
  const [doc, setDoc] = useState(null)
  const [tab, setTab] = useState(initialTab)

  useEffect(() => {
    setDoc(null)
    api.document(docId).then(setDoc)
  }, [docId])
  useEffect(() => { setTab(initialTab) }, [docId, initialTab])

  if (!doc) return <div className="panel loading">Loading {docId}…</div>
  const effectiveTab = tab === '3d' && !doc.model ? '2d' : tab

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
      </div>
      <div className="panel-body">
        {effectiveTab === '2d' && <PdfViewer url={doc.file_url} />}
        {effectiveTab === '3d' && <ModelViewer model={doc.model} />}
        {effectiveTab === 'detail' && <Evidence doc={doc} />}
      </div>
    </div>
  )
}

function Evidence({ doc }) {
  return (
    <div className="evidence">
      {doc.derivation && (
        <section>
          <h4>Degradation notice</h4>
          <p className="muted">{doc.derivation.modification_notice}</p>
        </section>
      )}
      <section>
        <h4>Candidate BOM rows</h4>
        {doc.bom_links.length === 0 && <p className="muted">No BOM row matched this drawing's name.</p>}
        <table>
          <thead><tr><th>Row</th><th>Name</th><th>Family</th><th>Material</th><th>Score</th><th>Method</th></tr></thead>
          <tbody>
            {doc.bom_links.map((l) => (
              <tr key={`${l.row_index}-${l.method}`}>
                <td>{l.row_index}</td><td>{l.name}</td><td>{l.part_family}</td><td>{l.material || '—'}</td>
                <td>{Math.round(l.score)}</td><td>{l.method} ({l.status})</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section>
        <h4>Drawing facts</h4>
        {doc.facts.length === 0 && <p className="muted">No fields extracted from this drawing yet.</p>}
        <ul>
          {doc.facts.map((f) => (
            <li key={f.id} className={f.status}>
              <b>{f.predicate}</b>: {f.value} <span className="muted">[{f.source_ref}] {f.status}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h4>Extracted text</h4>
        {doc.pages_text.map((p) => (
          <div key={p.page}>
            <div className="muted small">page {p.page} · {p.has_text_layer ? 'text layer' : 'no text layer (needs vision OCR)'}</div>
            {p.text && <pre className="text">{p.text}</pre>}
          </div>
        ))}
      </section>
      <section>
        <h4>Provenance</h4>
        <p className="small"><a href={doc.source_url} target="_blank" rel="noreferrer">{doc.source_url}</a></p>
        <p className="muted small">sha256 {doc.sha256}</p>
      </section>
    </div>
  )
}
