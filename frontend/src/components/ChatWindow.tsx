import { useEffect, useRef, useState } from 'react'
import { sendMessage } from '../api/chat'
import InputBar from './InputBar'
import MessageBubble from './MessageBubble'

interface Message {
  role: 'patient' | 'assistant'
  text: string
}

function getOrCreateSessionId(): string {
  const key = 'clinic_session_id'
  let id = sessionStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    sessionStorage.setItem(key, id)
  }
  return id
}

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sessionId = useRef<string>(getOrCreateSessionId())
  const bottomRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSubmit(text: string) {
    setLoading(true)
    setError(null)
    setMessages(prev => [...prev, { role: 'patient', text }])

    try {
      const reply = await sendMessage(sessionId.current, text)
      setMessages(prev => [...prev, { role: 'assistant', text: reply }])
    } catch (err: unknown) {
      const msg =
        typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Something went wrong. Please try again.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat-window">
      <header className="chat-window__header">
        <h1 className="chat-window__title">Super Clinic — Doctor&apos;s Assistant</h1>
      </header>

      <main className="chat-window__messages" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 && !loading && (
          <p className="chat-window__empty">
            Hello! How can I help you today? You can ask to book an appointment or describe your symptoms.
          </p>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} text={m.text} />
        ))}
        {loading && (
          <div className="chat-window__typing" aria-label="Assistant is typing">
            <span className="dot" /><span className="dot" /><span className="dot" />
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="chat-window__footer">
        <InputBar onSubmit={handleSubmit} loading={loading} error={error} />
      </footer>
    </div>
  )
}