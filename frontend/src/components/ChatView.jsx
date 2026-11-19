import { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import { api } from '../api.js'
import PartPanel from './PartPanel.jsx'

const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const renderMd = (s) => ({ __html: marked.parse(escapeHtml(s || '')) })

const EXAMPLES = [
  'Which subsystems are covered by the drawings?',
  'What material is the recoater plate made of, and who supplied it?',
  'Show me the build plate drawing.',
  'Which drawings are degraded scans?',
]

export default function ChatView({ onOpenInDrawings }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [active, setActive] = useState(null) // { document_id, tab }
  const endRef = useRef(null)

  // Braces matter: newer browsers return a Promise from scrollIntoView, which React would treat as a cleanup.
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  async function send(text) {
    const q = (text ?? input).trim()
    if (!q || busy) return
    const next = [...messages, { role: 'user', content: q }]
    setMessages(next)
    setInput('')
    setBusy(true)
    try {
      const res = await api.chat(next.map(({ role, content }) => ({ role, content })))
      setMessages([...next, { role: 'assistant', content: res.reply, meta: res }])
      // Chat drives the visual: open the first attached drawing, preferring 3D when present.
      const first = res.attachments.find((a) => a.type === 'drawing')
      if (first) {
        const has3d = res.attachments.some((a) => a.type === 'model3d' && a.document_id === first.document_id)
        setActive({ document_id: first.document_id, tab: has3d ? '3d' : '2d' })
      }
    } catch (e) {
      setMessages([...next, { role: 'assistant', content: `Error: ${e.message}`, error: true }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`chat-layout ${active ? 'with-panel' : ''}`}>
      <section className="chat">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <h2>Ask about the OpenLPBF v2 design evidence</h2>
              <p className="muted">Answers come from extracted drawing and BOM knowledge, with citations.</p>
              <div className="chips">
                {EXAMPLES.map((e) => (
                  <button key={e} className="chip" onClick={() => send(e)}>{e}</button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role} ${m.error ? 'error' : ''}`}>
              <div className="bubble" dangerouslySetInnerHTML={renderMd(m.content)} />
              {m.meta?.attachments?.length > 0 && (
                <div className="attachments">
                  {m.meta.attachments.map((a, j) => (
                    <button
                      key={j}
                      className={`attach ${a.type}`}
                      onClick={() => setActive({ document_id: a.document_id, tab: a.type === 'model3d' ? '3d' : '2d' })}
                    >
                      {a.type === 'model3d' ? '🧊 3D reconstruction' : '📄 Drawing'} · {a.document_id} {a.title}
                      {a.distribution === 'degraded-only' && <em className="tag warn">degraded</em>}
                    </button>
                  ))}
                </div>
              )}
              {m.meta && (
                <details className="trace">
                  <summary>
                    {m.meta.trace.length} tool call{m.meta.trace.length === 1 ? '' : 's'} · {m.meta.mode} · {m.meta.latency_ms} ms
                  </summary>
                  {m.meta.attempts?.map((a, k) => (
                    <pre key={`a${k}`}>{a.ok ? '✓' : '✗'} {a.model} {a.seconds}s{a.error ? ` — ${a.error}` : ''}</pre>
                  ))}
                  {m.meta.trace.map((t, k) => (
                    <pre key={k}>{t.tool}({JSON.stringify(t.args)}){'\n'}→ {t.result_preview}</pre>
                  ))}
                </details>
              )}
            </div>
          ))}
          {busy && <div className="msg assistant"><div className="bubble muted">Looking up evidence… (Gemini can take 10–60 s; overloaded models fall back automatically)</div></div>}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={(e) => { e.preventDefault(); send() }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about a part, material, supplier, interface… or propose a correction"
          />
          <button disabled={busy || !input.trim()}>Send</button>
        </form>
      </section>
      {active && (
        <aside className="side-panel">
          <PartPanel
            docId={active.document_id}
            initialTab={active.tab}
            onClose={() => setActive(null)}
            onExpand={() => onOpenInDrawings(active.document_id)}
          />
        </aside>
      )}
    </div>
  )
}
