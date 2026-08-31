import { useRef, useState } from 'react'
import MessageList from './components/MessageList'
import MessageInput from './components/MessageInput'
import SuggestedQuestions from './components/SuggestedQuestions'
import AssumptionsPanel from './components/AssumptionsPanel'
import './App.css'

// Overridable for demos from another machine or network — see
// frontend/.env.example. Vite inlines this at build time, so a change needs a
// dev-server restart or a rebuild. The fallback keeps local dev working with
// no .env present.
const CHAT_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/chat'

function App() {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const isSendingRef = useRef(false)

  async function handleSend(text) {
    if (isSendingRef.current) return
    isSendingRef.current = true
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setIsLoading(true)

    try {
      const res = await fetch(CHAT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      })

      if (!res.ok) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'error',
            content: `The backend returned an error (HTTP ${res.status}) — check the server logs (a missing or invalid ANTHROPIC_API_KEY is a common cause).`,
          },
        ])
        return
      }

      const data = await res.json()
      setSessionId(data.session_id)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }])
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'error',
          content:
            'Could not reach the backend. Make sure the API server is running (uvicorn backend.main:app --port 8000) and try again.',
        },
      ])
    } finally {
      setIsLoading(false)
      isSendingRef.current = false
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Airport Investment Intelligence Agent</h1>
      </header>
      <AssumptionsPanel />
      <MessageList messages={messages} isLoading={isLoading} />
      {messages.length === 0 && (
        <SuggestedQuestions onSelect={handleSend} disabled={isLoading} />
      )}
      <MessageInput onSend={handleSend} isLoading={isLoading} />
    </div>
  )
}

export default App
