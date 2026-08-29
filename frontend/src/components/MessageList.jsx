import ReactMarkdown from 'react-markdown'

function MessageList({ messages, isLoading }) {
  return (
    <div className="message-list">
      {messages.map((msg, i) => (
        <div key={i} className={`message ${msg.role}`}>
          {msg.role === 'assistant' ? (
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          ) : (
            msg.content
          )}
        </div>
      ))}
      {isLoading && <div className="message thinking">thinking...</div>}
    </div>
  )
}

export default MessageList
