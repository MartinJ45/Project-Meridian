import { useEffect, useState } from 'react'
import { api } from './api.js'
import ChatView from './components/ChatView.jsx'
import DocumentsView from './components/DocumentsView.jsx'
import ReviewView from './components/ReviewView.jsx'
import { ChatIcon, DocumentIcon, PlusIcon, ReviewIcon, UserIcon } from './components/Icons.jsx'

const VIEWS = [
  { id: 'chat', label: 'Chat', Icon: ChatIcon },
  { id: 'documents', label: 'Drawings', Icon: DocumentIcon },
  { id: 'review', label: 'Review corrections', Icon: ReviewIcon },
]

export default function App() {
  const [view, setView] = useState('chat')
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [chatKey, setChatKey] = useState(0) // bump to start a new chat
  // Shared so a drawing opened from chat can also be opened in the Drawings view.
  const [selectedDoc, setSelectedDoc] = useState(null)

  // Connectivity: "offline" only when the browser has no network or the app server is unreachable.
  const [browserOnline, setBrowserOnline] = useState(() => navigator.onLine)
  const [serverReachable, setServerReachable] = useState(true)

  useEffect(() => {
    const check = () =>
      api.health()
        .then((h) => { setHealth(h); setError(null); setServerReachable(true) })
        .catch((e) => { setError(e.message); setServerReachable(false) })
    check()
    const timer = setInterval(check, 30000)
    const goOnline = () => { setBrowserOnline(true); check() }
    const goOffline = () => setBrowserOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      clearInterval(timer)
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [view])

  const online = browserOnline && serverReachable

  const openInDrawings = (docId) => {
    setSelectedDoc(docId)
    setView('documents')
  }
  const newChat = () => {
    setChatKey((k) => k + 1)
    setView('chat')
  }

  return (
    <div className="app">
      <nav className="rail" aria-label="Main">
        <button className="rail-btn" onClick={newChat} title="New chat" aria-label="New chat">
          <PlusIcon />
        </button>
        {VIEWS.map(({ id, label, Icon }) => (
          <button
            key={id}
            className={`rail-btn ${view === id ? 'active' : ''}`}
            onClick={() => setView(id)}
            title={label}
            aria-label={label}
            aria-current={view === id ? 'page' : undefined}
          >
            <Icon />
            {id === 'review' && health?.corrections_pending > 0 && (
              <i className="badge">{health.corrections_pending}</i>
            )}
          </button>
        ))}
        <div className="rail-foot" title="Profile">
          <UserIcon />
        </div>
      </nav>
      <main className="main">
        {error && <div className="banner error">Backend error: {error}</div>}
        {/* Chat stays mounted (just hidden) so switching views keeps the conversation. */}
        <div className="view" hidden={view !== 'chat'}>
          <ChatView key={chatKey} online={online} onOpenInDrawings={openInDrawings} />
        </div>
        {view === 'documents' && <div className="view"><DocumentsView selected={selectedDoc} onSelect={setSelectedDoc} /></div>}
        {view === 'review' && <div className="view"><ReviewView /></div>}
      </main>
    </div>
  )
}
