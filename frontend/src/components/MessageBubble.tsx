interface MessageBubbleProps {
  role: 'patient' | 'assistant'
  text: string
}

export default function MessageBubble({ role, text }: MessageBubbleProps) {
  const isPatient = role === 'patient'
  return (
    <div
      className={`bubble bubble--${role}`}
      aria-label={isPatient ? 'Your message' : 'Assistant message'}
    >
      <span className="bubble__label">{isPatient ? 'You' : 'Assistant'}</span>
      <p className="bubble__text">{text}</p>
    </div>
  )
}