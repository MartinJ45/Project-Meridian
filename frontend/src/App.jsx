import { useEffect, useState } from 'react'
import { api } from './api.js'
import ChatView from './components/ChatView.jsx'
import DocumentsView from './components/DocumentsView.jsx'
import ReviewView from './components/ReviewView.jsx'

const VIEWS = [
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'documents', label: 'Drawings', icon: '📄' },
  { id: 'review', label: 'Review', icon: '✔' },
]

export default function App() {
  const [view, setView] = useState('chat')
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  // Shared so a drawing opened from chat can also be opened in the Drawings view.
  const [selectedDoc, setSelectedDoc] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(e.message))
  }, [view])

  const openInDrawings = (docId) => {
    setSelectedDoc(docId)
    setView('documents')
  }

  return (
    <div className="app">
      <nav className="rail">
        <div className="logo">M</div>
        {VIEWS.map((v) => (
          <button
            key={v.id}
            className={`rail-btn ${view === v.id ? 'active' : ''}`}
            onClick={() => setView(v.id)}
            title={v.label}
          >
            <span>{v.icon}</span>
            <small>{v.label}</small>
            {v.id === 'review' && health?.corrections_pending > 0 && (
              <i className="badge">{health.corrections_pending}</i>
            )}
          </button>
        ))}
        <div className="rail-foot" title={health ? `model: ${health.model}` : ''}>
          <span className={`dot ${health?.gemini_configured ? 'ok' : 'warn'}`} />
          <small>{health?.gemini_configured ? 'Gemini' : 'Offline'}</small>
        </div>
      </nav>
      <main className="main">
        {error && <div className="banner error">Backend error: {error}</div>}
        {view === 'chat' && <ChatView onOpenInDrawings={openInDrawings} />}
        {view === 'documents' && <DocumentsView selected={selectedDoc} onSelect={setSelectedDoc} />}
        {view === 'review' && <ReviewView />}
      </main>
    </div>
  )
}
