import { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import { api } from '../api.js'

const logo = '/avathon-logo.png' // from the repo-level assets/ folder (Vite publicDir)
import PartPanel from './PartPanel.jsx'
import { CopyIcon, SendIcon } from './Icons.jsx'

const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const renderMd = (s) => ({ __html: marked.parse(escapeHtml(s || '')) })

const EXAMPLES = [
  'Which subsystems are covered by the drawings?',
  'What material is the recoater mount block, and who supplied it?',
  'Show me the cylinder clamp ring.',
  'Which drawings are degraded scans?',
]

// Shown one after another while waiting for an answer. The backend does these steps
// (retrieve evidence, then one model call), so the messages describe real work.
function progressSteps(question) {
  const q = question.toLowerCase()
  const steps = ['Searching drawings and the BOM…', 'Matching parts to drawings…']
  if (/material|alloy|alu|steel/.test(q)) steps.push('Fetching recorded materials…')
  if (/supplier|cost|price|order|dkk/.test(q)) steps.push('Fetching supplier and cost records…')
  if (/wrong|incorrect|should be|correct/.test(q)) steps.push('Checking the proposed correction…')
  if (/degraded|scan|noisy|clean/.test(q)) steps.push('Checking drawing quality…')
  steps.push('Gathering evidence and citations…', 'Writing the answer…', 'Still working, almost there…')
  return steps
}

function Avatar() {
  return (
    <div className="avatar" aria-hidden="true">
      <img src={logo} alt="" />
    </div>
  )
}

// The panel to show for an answer: its first drawing, on the 3D tab when a reconstruction exists.
function panelFor(attachments = []) {
  const first = attachments.find((a) => a.type === 'drawing')
  if (!first) return null
  if (first.tab) return { document_id: first.document_id, tab: first.tab } // e.g. 'suppliers'
  const has3d = attachments.some((a) => a.type === 'model3d' && a.document_id === first.document_id)
  return { document_id: first.document_id, tab: has3d ? '3d' : '2d' }
}

// chatId: the stored chat to show (null = new chat). Mounted fresh for each chat (keyed in App).
export default function ChatView({
  chatId, online, onChatCreated, onChatMissing, onOpenInDrawings, onOpenGraph, pendingQuestion, onPendingConsumed,
}) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(!!chatId)
  const [progress, setProgress] = useState('')
  const [active, setActive] = useState(null) // { document_id, tab }
  const endRef = useRef(null)
  const chatIdRef = useRef(chatId)

  // Reopen a stored chat (after a refresh or from Past chats), including its last drawing panel.
  useEffect(() => {
    if (!chatId) return
    let cancelled = false
    api.getChat(chatId)
      .then((chat) => {
        if (cancelled) return
        setMessages(chat.messages.map((m) => ({ role: m.role, content: m.content, meta: m.meta })))
        const lastWithDrawing = [...chat.messages].reverse().find((m) => panelFor(m.meta?.attachments))
        if (lastWithDrawing) setActive(panelFor(lastWithDrawing.meta.attachments))
      })
      .catch(() => { if (!cancelled) onChatMissing?.() }) // deleted or unknown id: start fresh
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Braces matter: newer browsers return a Promise from scrollIntoView, which React would treat as a cleanup.
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, progress])

  // A question asked from another view (e.g. "Ask in chat" in the graph) is sent here.
  useEffect(() => {
    if (pendingQuestion && !busy && !loading) {
      onPendingConsumed?.()
      send(pendingQuestion)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion, busy, loading])

  async function send(text) {
    const q = (text ?? input).trim()
    if (!q || busy || loading) return
    const next = [...messages, { role: 'user', content: q }]
    setMessages(next)
    setInput('')
    setBusy(true)
    const steps = progressSteps(q)
    let i = 0
    setProgress(steps[0])
    const timer = setInterval(() => {
      i = Math.min(i + 1, steps.length - 1)
      setProgress(steps[i])
    }, 2500)
    try {
      // The server keeps the history; we send only the new message and the chat id.
      const res = await api.chat(q, chatIdRef.current)
      if (!chatIdRef.current) {
        chatIdRef.current = res.chat_id
        onChatCreated?.(res.chat_id)
      }
      setMessages([...next, { role: 'assistant', content: res.reply, meta: res }])
      // Chat drives the visual: open the first attached drawing, preferring 3D when present.
      const panel = panelFor(res.attachments)
      if (panel) setActive(panel)
    } catch (e) {
      setMessages([...next, { role: 'assistant', content: `Something went wrong: ${e.message}`, error: true }])
    } finally {
      clearInterval(timer)
      setBusy(false)
      setProgress('')
    }
  }

  return (
    <div className={`chat-layout ${active ? 'with-panel' : ''}`}>
      <section className="chat">
        <div className="messages">
          <div className="column">
            {loading && <div className="empty muted">Loading chat…</div>}
            {!loading && messages.length === 0 && (
              <div className="empty">
                <img className="empty-logo" src={logo} alt="" />
                <h2>Ask about the OpenLPBF v2 design evidence</h2>
                <p className="muted">Answers come from extracted drawing and BOM knowledge, with citations.</p>
                <div className="chips">
                  {EXAMPLES.map((e) => (
                    <button key={e} className="chip" onClick={() => send(e)}>{e}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="msg user">
                  <div className="bubble">{m.content}</div>
                </div>
              ) : (
                <div key={i} className={`msg assistant ${m.error ? 'error' : ''}`}>
                  <Avatar />
                  <div className="msg-body">
                    <div className="bubble" dangerouslySetInnerHTML={renderMd(m.content)} />
                    {m.meta?.attachments?.length > 0 && (
                      <div className="attachments">
                        {m.meta.attachments.map((a, j) => a.type === 'graph' ? (
                          <button key={j} className="attach graph" onClick={() => onOpenGraph?.(a.focus)}>
                            Knowledge graph · around {a.label}
                          </button>
                        ) : (
                          <button
                            key={j}
                            className={`attach ${a.type}`}
                            onClick={() => setActive({ document_id: a.document_id, tab: a.type === 'model3d' ? '3d' : '2d' })}
                          >
                            {a.type === 'model3d' ? '3D reconstruction' : 'Drawing'} · {a.document_id} {a.title}
                            {a.distribution === 'degraded-only' && <em className="tag warn">degraded</em>}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="msg-tools">
                      <button className="icon-btn" title="Copy answer" aria-label="Copy answer"
                        onClick={() => navigator.clipboard?.writeText(m.content)}>
                        <CopyIcon />
                      </button>
                      {m.meta && (
                        <details className="trace">
                          <summary>
                            {m.meta.trace.length} step{m.meta.trace.length === 1 ? '' : 's'} · {(m.meta.latency_ms / 1000).toFixed(1)} s
                          </summary>
                          {m.meta.trace.map((t, k) => (
                            <pre key={k}>{t.tool}({JSON.stringify(t.args)}){'\n'}→ {t.result_preview}</pre>
                          ))}
                        </details>
                      )}
                    </div>
                  </div>
                </div>
              )
            )}
            {busy && (
              <div className="msg assistant">
                <Avatar />
                <div className="msg-body">
                  <div className="bubble thinking" aria-live="polite">
                    <span className="pulse" />
                    {progress}
                  </div>
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>
        <div className="composer-wrap">
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send() }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Enter your prompt here…"
              aria-label="Message"
            />
            <button className="send" disabled={busy || !input.trim()} title="Send" aria-label="Send">
              <SendIcon />
            </button>
          </form>
          <div className="composer-foot">
            <div className="status-pill" title={online ? 'Connected' : 'No connection to the network or the Meridian server'}>
              <span className={`dot ${online ? 'ok' : 'warn'}`} />
              <span>Meridian · {online ? 'Online' : 'Offline'}</span>
            </div>
          </div>
        </div>
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
