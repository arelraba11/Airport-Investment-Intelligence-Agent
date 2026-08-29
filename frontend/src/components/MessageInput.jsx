import { useState } from 'react'

function MessageInput({ onSend, isLoading }) {
  const [value, setValue] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || isLoading) return
    onSend(trimmed)
    setValue('')
  }

  return (
    <form className="message-input-form" onSubmit={handleSubmit}>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask about an airport..."
        disabled={isLoading}
      />
      <button type="submit" disabled={isLoading}>
        Send
      </button>
    </form>
  )
}

export default MessageInput
