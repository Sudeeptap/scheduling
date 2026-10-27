import { useRef } from 'react'

interface InputBarProps {
  onSubmit: (text: string) => void
  loading: boolean
  error: string | null
}

export default function InputBar({ onSubmit, loading, error }: InputBarProps) {
  const ref = useRef<HTMLTextAreaElement>(null)

  function handleSubmit() {
    const value = ref.current?.value.trim() ?? ''
    if (!value || loading) return
    onSubmit(value)
    if (ref.current) ref.current.value = ''
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="input-bar">
      {error && (
        <p className="input-bar__error" role="alert" aria-live="polite">
          {error}
        </p>
      )}
      <div className="input-bar__row">
        <label htmlFor="chat-input" className="sr-only">
          Type your message
        </label>
        <textarea
          id="chat-input"
          ref={ref}
          className="input-bar__textarea"
          placeholder="Type a message… (Enter to send, Shift+Enter for new line)"
          disabled={loading}
          onKeyDown={handleKeyDown}
          rows={2}
          aria-disabled={loading}
        />
        <button
          className="input-bar__send"
          onClick={handleSubmit}
          disabled={loading}
          aria-label="Send message"
        >
          {loading ? '…' : 'Send'}
        </button>
      </div>
    </div>
  )
}