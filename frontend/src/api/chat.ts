/**
 * API helper for POST /chat.
 * The OpenAI key is never included here — it lives on the backend only.
 */

export interface ChatApiError {
  status: number
  message: string
}

export async function sendMessage(
  sessionId: string,
  message: string,
): Promise<string> {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })

  if (!res.ok) {
    let detail = `Request failed (HTTP ${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // ignore JSON parse error; use default message
    }
    const err: ChatApiError = { status: res.status, message: detail }
    throw err
  }

  const data = await res.json()
  return data.reply as string
}