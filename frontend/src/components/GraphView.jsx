import { useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { api } from '../api.js'

const KINDS = {
  subsystem: { label: 'Subsystems', color: '#1e293b', size: 46 },
  family: { label: 'BOM families', color: '#64748b', size: 34 },
  drawing: { label: 'Drawings', color: '#2563eb', size: 26 },
  part: { label: 'Parts (BOM rows)', color: '#059669', size: 20 },
  material: { label: 'Materials', color: '#d97706', size: 32 },
  supplier: { label: 'Suppliers (recorded)', color: '#9333ea', size: 22 },
}

const REL_LABEL = {
  in_subsystem: 'in subsystem', in_family: 'in BOM family', mostly_in: 'family mostly in', depicts: 'drawing of',
  interfaces: 'interfaces with', specifies: 'drawing specifies', records: 'BOM records', supplied_by: 'supplied by',
}

// Default: everything except suppliers, and only parts that have a drawing or interfaces.
const DEFAULT_SHOW = { subsystem: true, family: true, drawing: true, part: true, material: true, supplier: false }

export default function GraphView({ focus: focusProp, onOpenDrawing, onAsk }) {
  const hostRef = useRef(null)
  const cyRef = useRef(null)
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)
  const [show, setShow] = useState(DEFAULT_SHOW)
  const [allParts, setAllParts] = useState(false)
  const [focus, setFocus] = useState(focusProp || null)
  const [depth, setDepth] = useState(1)
  const [selected, setSelected] = useState(focusProp || null)
  const [q, setQ] = useState('')

  useEffect(() => { api.graph().then(setGraph).catch((e) => setError(e.message)) }, [])
  useEffect(() => { if (focusProp) { setFocus(focusProp); setSelected(focusProp) } }, [focusProp])

  const byId = useMemo(() => Object.fromEntries((graph?.nodes || []).map((n) => [n.id, n])), [graph])

  // Which nodes/edges to draw for the current filters and focus.
  const visible = useMemo(() => {
    if (!graph) return null
    let ids
    if (focus && byId[focus]) {
      const adj = {}
      for (const e of graph.edges) {
        ;(adj[e.source] ||= new Set()).add(e.target)
        ;(adj[e.target] ||= new Set()).add(e.source)
      }
      ids = new Set([focus])
      let frontier = new Set([focus])
      for (let i = 0; i < depth; i++) {
        const next = new Set()
        frontier.forEach((n) => adj[n]?.forEach((m) => { if (!ids.has(m)) next.add(m) }))
        next.forEach((m) => ids.add(m))
        frontier = next
      }
      ids = new Set([...ids].filter((id) => id === focus || show[byId[id].kind]))
    } else {
      ids = new Set(graph.nodes.filter((n) => show[n.kind] &&
        (n.kind !== 'part' || allParts || n.has_drawing || n.has_interfaces)).map((n) => n.id))
    }
    const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target))
    return { nodes: [...ids].map((id) => byId[id]), edges }
  }, [graph, byId, show, allParts, focus, depth])

  // (Re)draw.
  useEffect(() => {
    if (!visible || !hostRef.current) return
    cyRef.current?.destroy()
    const cy = cytoscape({
      container: hostRef.current,
      elements: [
        ...visible.nodes.map((n) => ({ data: { ...n, color: KINDS[n.kind].color, size: KINDS[n.kind].size } })),
        ...visible.edges.map((e) => ({ data: e })),
      ],
      style: [
        { selector: 'node', style: {
          'background-color': 'data(color)', width: 'data(size)', height: 'data(size)', label: 'data(label)',
          'font-size': 9, color: '#0f172a', 'text-valign': 'bottom', 'text-margin-y': 3, 'text-wrap': 'ellipsis',
          'text-max-width': 110, 'min-zoomed-font-size': 7 } },
        { selector: 'node[kind = "subsystem"]', style: { 'font-size': 12, 'font-weight': 600, shape: 'round-rectangle' } },
        { selector: 'node[kind = "material"]', style: { shape: 'diamond', 'font-size': 11 } },
        { selector: 'node[kind = "family"]', style: { shape: 'round-rectangle' } },
        { selector: 'node[?degraded]', style: { 'border-width': 3, 'border-color': '#f59e0b' } },
        { selector: 'node[?has_model]', style: { 'border-width': 3, 'border-color': '#8b5cf6' } },
        { selector: 'edge', style: { width: 1, 'line-color': '#cbd5e1', 'curve-style': 'bezier', opacity: 0.8 } },
        { selector: 'edge[rel = "depicts"]', style: { width: 2.5, 'line-color': '#2563eb' } },
        { selector: 'edge[status = "probable"]', style: { 'line-style': 'dashed' } },
        { selector: 'edge[?conflict]', style: { 'line-color': '#dc2626', width: 3.5 } },
        { selector: 'edge[rel = "interfaces"]', style: { 'line-color': '#059669', width: 2,
          'target-arrow-shape': 'triangle', 'target-arrow-color': '#059669', 'arrow-scale': 0.8 } },
        { selector: ':selected', style: { 'border-width': 4, 'border-color': '#ef4444' } },
      ],
      layout: { name: 'null' },
      wheelSensitivity: 0.25,
    })
    // cose starts from random positions; seed the RNG while it runs (synchronously, animate: false)
    // so the same graph always lays out the same way.
    const random = Math.random
    Math.random = seededRandom(42)
    try {
      cy.layout({ name: 'cose', animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 60,
        nodeOverlap: 12, padding: 20, randomize: true,
        // fixed area so the result does not depend on the pane size at mount time; fit() then scales it
        boundingBox: { x1: 0, y1: 0, w: 1400, h: 900 } }).run()
    } finally {
      Math.random = random
    }
    cy.on('tap', 'node', (ev) => setSelected(ev.target.id()))
    cy.on('tap', (ev) => { if (ev.target === cy) setSelected(null) })
    if (selected && cy.getElementById(selected).length) cy.getElementById(selected).select()
    cyRef.current = cy
    // The pane may not have its final size yet (e.g. right after a page refresh): fit the graph
    // once it does, and keep the canvas in sync with later size changes.
    const host = hostRef.current
    let fitted = host.clientWidth > 0 && host.clientHeight > 0
    const ro = new ResizeObserver(() => {
      if (!host.clientWidth || !host.clientHeight) return
      cy.resize()
      if (!fitted) { cy.fit(undefined, 20); fitted = true }
    })
    ro.observe(host)
    return () => { ro.disconnect(); cy.destroy() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.$(':selected').unselect()
    if (selected && cy.getElementById(selected).length) {
      const n = cy.getElementById(selected)
      n.select()
      cy.animate({ center: { eles: n }, duration: 250 })
    }
  }, [selected])

  const search = (e) => {
    e.preventDefault()
    const t = q.trim().toLowerCase()
    if (!t || !graph) return
    const hit = graph.nodes.find((n) => n.label.toLowerCase().includes(t) || n.id.toLowerCase().includes(t))
    if (hit) { setFocus(hit.id); setSelected(hit.id) }
  }

  const sel = selected && byId[selected]
  const selEdges = sel ? graph.edges.filter((e) => e.source === sel.id || e.target === sel.id) : []

  if (error) return <div className="banner error">Could not load the graph: {error}</div>
  return (
    <div className="graph-layout">
      <div className="graph-main">
        <div className="graph-toolbar">
          <form onSubmit={search}>
            <input placeholder="Find a part, drawing, material…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find in graph" />
          </form>
          {Object.entries(KINDS).map(([k, v]) => (
            <label key={k} className="kind-toggle">
              <input type="checkbox" checked={show[k]} onChange={() => setShow({ ...show, [k]: !show[k] })} />
              <span className="swatch" style={{ background: v.color }} /> {v.label}
            </label>
          ))}
          {!focus && (
            <label className="kind-toggle" title="Include BOM rows without a drawing or interfaces">
              <input type="checkbox" checked={allParts} onChange={() => setAllParts(!allParts)} /> all 192 parts
            </label>
          )}
          {focus && (
            <span className="focus-chip">
              Around <b>{byId[focus]?.label}</b>
              <select value={depth} onChange={(e) => setDepth(+e.target.value)} aria-label="Depth">
                <option value={1}>1 step</option><option value={2}>2 steps</option><option value={3}>3 steps</option>
              </select>
              <button onClick={() => setFocus(null)}>Show all</button>
            </span>
          )}
        </div>
        <div className="graph-canvas" ref={hostRef} />
        <div className="graph-legend small muted">
          <span><i className="lg-line blue" /> drawing of (reviewed link)</span>
          <span><i className="lg-line blue dashed" /> probable link</span>
          <span><i className="lg-line red" /> link with a drawing/BOM conflict</span>
          <span><i className="lg-line green" /> interfaces with</span>
          <span><i className="lg-ring amber" /> degraded scan</span>
          <span><i className="lg-ring violet" /> has 3D</span>
          {visible && <span>{visible.nodes.length} nodes · {visible.edges.length} edges</span>}
        </div>
      </div>
      <aside className="graph-side">
        {!sel && (
          <div className="muted small">
            <p>Click a node to see its connections and where each one comes from.</p>
            <p>{graph ? `${graph.nodes.length} nodes and ${graph.edges.length} edges, built from the BOM, the extracted drawings, reviewed links and consistency checks.` : 'Loading…'}</p>
          </div>
        )}
        {sel && (
          <div>
            <div className="muted small">{KINDS[sel.kind].label.replace(/s( \(.*\))?$/, '')}</div>
            <h3 className="graph-title">{sel.label}</h3>
            <div className="graph-actions">
              {sel.kind === 'drawing' && <button onClick={() => onOpenDrawing(sel.doc_id)}>Open drawing</button>}
              <button onClick={() => { setFocus(sel.id) }}>Focus here</button>
              <button onClick={() => onAsk(questionFor(sel))}>Ask in chat</button>
            </div>
            {sel.kind === 'drawing' && (
              <p className="small">Link: <b>{sel.link_status}</b>{sel.degraded ? ' · degraded scan' : ''}{sel.has_model ? ' · 3D reconstruction' : ''}</p>
            )}
            {sel.kind === 'part' && <p className="small">BOM row {sel.row} · {sel.type || '—'} · {sel.family || '—'}</p>}
            <h4>Connections ({selEdges.length})</h4>
            <ul className="graph-edges">
              {selEdges.slice(0, 80).map((e) => {
                const other = byId[e.source === sel.id ? e.target : e.source]
                return (
                  <li key={e.id} className={e.conflict ? 'conflict' : ''}>
                    <button className="link-btn" onClick={() => setSelected(other.id)}>{other.label}</button>
                    <span className="muted"> · {REL_LABEL[e.rel] || e.rel}{e.source !== sel.id ? ' (incoming)' : ''}</span>
                    <div className="muted small">{e.basis}</div>
                    {e.checks?.filter((c) => c.verdict !== 'agree').map((c, i) => (
                      <div key={i} className={`small ${c.verdict === 'conflict' ? 'bad-text' : 'muted'}`}>
                        {c.field}: {c.verdict.replaceAll('_', ' ')} — {c.detail}
                      </div>
                    ))}
                  </li>
                )
              })}
              {selEdges.length > 80 && <li className="muted small">… {selEdges.length - 80} more</li>}
            </ul>
          </div>
        )}
      </aside>
    </div>
  )
}

function questionFor(n) {
  if (n.kind === 'drawing') return `Tell me about drawing ${n.doc_id} and how it relates to the BOM.`
  if (n.kind === 'part') return `Tell me about BOM row ${n.row} (${n.label}): drawings, interfaces, material and supplier.`
  if (n.kind === 'material') return `Which parts and drawings use ${n.label}?`
  if (n.kind === 'supplier') return `Which parts does the BOM record as supplied by ${n.label}?`
  if (n.kind === 'subsystem') return `What drawings and parts belong to the ${n.label} subsystem?`
  return `Tell me about the ${n.label} BOM family.`
}

// Small deterministic PRNG (mulberry32) so the graph layout is reproducible.
function seededRandom(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
