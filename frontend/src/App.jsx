import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import ChatView from './components/ChatView.jsx'
import DocumentsView from './components/DocumentsView.jsx'
import HistoryView from './components/HistoryView.jsx'
import ReviewView from './components/ReviewView.jsx'
import { ChatIcon, DocumentIcon, HistoryIcon, PlusIcon, ReviewIcon, UserIcon } from './components/Icons.jsx'

const VIEWS = [
  { id: 'chat', label: 'Chat', Icon: ChatIcon },
  { id: 'history', label: 'Past chats', Icon: HistoryIcon },
  { id: 'documents', label: 'Drawings', Icon: DocumentIcon },
  { id: 'review', label: 'Review corrections', Icon: ReviewIcon },
]

// The open chat lives in the URL (#/chat/<id>) so a page refresh reopens it.
const chatIdFromHash = () => window.location.hash.match(/^#\/chat\/([\w-]+)$/)?.[1] ?? null

export default function App() {
  const [view, setView] = useState('chat')
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [chatId, setChatId] = useState(chatIdFromHash)
  const chatIdRef = useRef(chatId)
  const [chatKey, setChatKey] = useState(0) // bump to remount ChatView (new or different chat)
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

  const switchChat = useCallback((id) => {
    chatIdRef.current = id
    setChatId(id)
    setChatKey((k) => k + 1)
    setView('chat')
  }, [])

  // Back/forward buttons and manually edited URLs.
  useEffect(() => {
    const onHash = () => {
      const id = chatIdFromHash()
      if (id !== chatIdRef.current) switchChat(id)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [switchChat])

  const openChat = (id) => {
    if (id === chatIdRef.current) { setView('chat'); return }
    window.location.hash = `#/chat/${id}` // hashchange -> switchChat
  }
  const newChat = () => {
    window.history.pushState(null, '', window.location.pathname + window.location.search)
    switchChat(null)
  }
  // The first message of a new chat created it on the server: record the id without remounting.
  const onChatCreated = (id) => {
    chatIdRef.current = id
    setChatId(id)
    window.history.replaceState(null, '', `#/chat/${id}`)
  }

  const openInDrawings = (docId) => {
    setSelectedDoc(docId)
    setView('documents')
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
          <ChatView
            key={chatKey}
            chatId={chatId}
            online={online}
            onChatCreated={onChatCreated}
            onChatMissing={newChat}
            onOpenInDrawings={openInDrawings}
          />
        </div>
        {view === 'history' && (
          <div className="view">
            <HistoryView currentId={chatId} onOpen={openChat} onDeletedCurrent={newChat} onNew={newChat} />
          </div>
        )}
        {view === 'documents' && <div className="view"><DocumentsView selected={selectedDoc} onSelect={setSelectedDoc} /></div>}
        {view === 'review' && <div className="view"><ReviewView /></div>}
      </main>
    </div>
  )
}
