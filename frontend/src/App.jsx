import { useState } from 'react'
import MessageList from './components/MessageList'
import MessageInput from './components/MessageInput'
import './App.css'

function App() {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(() => crypto.randomUUID())

  function handleSend(text) {
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setIsLoading(true)

    // Temporary local stub for B.1 — real fetch to POST /chat lands in B.2.
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `This is a placeholder reply. Backend wiring lands in Phase B.2.\n\n(session: \`${sessionId}\`)`,
        },
      ])
      setIsLoading(false)
    }, 800)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>Airport Investment Intelligence Agent</h1>
      </header>
      <MessageList messages={messages} isLoading={isLoading} />
      <MessageInput onSend={handleSend} isLoading={isLoading} />
    </div>
  )
}

export default App
