import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, keycloak } from './auth'

type Identity = { id: string; username: string; display_name: string; roles: string[] }
type Conversation = { id: string; title: string; mode: 'direct'; messages?: Message[] }
type Message = { id: string; turn_id?: string; role: 'user' | 'assistant'; content: string; status: string }
type Turn = { turn_id: string; state: string; events_url: string; correlation_id: string }
type StreamEvent = { sequence: number; type: string; payload: Record<string, string> }

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: `Request failed (${response.status})` }))
    throw new Error(body.detail ?? `Request failed (${response.status})`)
  }
  return response.json()
}

export function App({ authenticated }: { authenticated: boolean }) {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [draft, setDraft] = useState('')
  const [turn, setTurn] = useState<Turn | null>(null)
  const [streamText, setStreamText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const streamAbort = useRef<AbortController | null>(null)

  const loadConversations = useCallback(async () => {
    const items = await json<Conversation[]>('/api/v1/conversations')
    setConversations(items)
    return items
  }, [])

  const openConversation = useCallback(async (id: string) => {
    streamAbort.current?.abort()
    setTurn(null)
    setStreamText('')
    setError(null)
    const item = await json<Conversation>(`/api/v1/conversations/${id}`)
    setActive(item)
    window.history.replaceState({}, '', `/chat/${id}`)
  }, [])

  useEffect(() => {
    if (!authenticated) return
    Promise.all([json<Identity>('/api/v1/me'), loadConversations()])
      .then(([me, items]) => {
        setIdentity(me)
        const routeId = window.location.pathname.match(/^\/chat\/([^/]+)$/)?.[1]
        if (routeId) openConversation(routeId).catch((reason: Error) => setError(reason.message))
        else if (items[0]) openConversation(items[0].id).catch((reason: Error) => setError(reason.message))
      })
      .catch((reason: Error) => setError(reason.message))
  }, [authenticated, loadConversations, openConversation])

  async function createConversation() {
    const item = await json<Conversation>('/api/v1/conversations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New conversation', mode: 'direct' }),
    })
    setConversations((current) => [item, ...current])
    setActive({ ...item, messages: [] })
    setTurn(null)
    setStreamText('')
    window.history.replaceState({}, '', `/chat/${item.id}`)
  }

  async function consumeEvents(created: Turn, conversationId: string, after = 0) {
    const controller = new AbortController()
    streamAbort.current = controller
    const response = await apiFetch(`${created.events_url}?after=${after}`, { signal: controller.signal })
    if (!response.ok || !response.body) throw new Error(`Event stream failed (${response.status})`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const data = frame.split('\n').find((line) => line.startsWith('data: '))
        if (!data) continue
        const event = JSON.parse(data.slice(6)) as StreamEvent
        if (event.type === 'assistant.delta') setStreamText((value) => value + event.payload.delta)
        if (event.type === 'turn.failed') setError(`${event.payload.message} Reference: ${event.payload.correlation_id}`)
        if (['turn.completed', 'turn.failed', 'turn.cancelled'].includes(event.type)) {
          setTurn((current) => current ? { ...current, state: event.type.slice(5) } : current)
        }
      }
    }
    await openConversation(conversationId)
    await loadConversations()
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || !active || turn && ['accepted', 'running'].includes(turn.state)) return
    setDraft('')
    setError(null)
    setStreamText('')
    setActive({ ...active, messages: [...(active.messages ?? []), {
      id: crypto.randomUUID(), role: 'user', content, status: 'complete',
    }] })
    try {
      const created = await json<Turn>(`/api/v1/conversations/${active.id}/turns`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, idempotency_key: crypto.randomUUID() }),
      })
      setTurn(created)
      await consumeEvents(created, active.id)
    } catch (reason) {
      if ((reason as Error).name !== 'AbortError') setError((reason as Error).message)
    }
  }

  async function cancel() {
    if (!turn) return
    await json(`/api/v1/turns/${turn.turn_id}/cancel`, { method: 'POST' })
  }

  if (!authenticated) return (
    <main className="landing"><nav><span className="brand">PORFIRIUM</span><span className="status">Phase 2</span></nav>
      <section className="hero"><p className="eyebrow">A durable, observable AI workspace</p>
        <h1>One place to talk,<br /><em>build, and inspect.</em></h1>
        <p className="lede">Stream direct model conversations through your private, local-first workspace.</p>
        <button onClick={() => keycloak.login()}>Sign in with Keycloak <span>↗</span></button></section>
      <footer><span>Identity protected</span><span>Local-first</span><span>Phase 2 / 5</span></footer></main>
  )

  const busy = turn && ['accepted', 'running'].includes(turn.state)
  return <main className="app-shell">
    <aside><div className="brand">PORFIRIUM</div>
      <button className="new-chat" onClick={() => createConversation().catch((reason) => setError(reason.message))}>＋ New conversation</button>
      <div className="conversation-list">{conversations.map((item) =>
        <button className={active?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => openConversation(item.id).catch((reason) => setError(reason.message))}>{item.title}</button>)}</div>
      <div className="profile"><div className="avatar">{identity?.display_name?.[0] ?? '…'}</div>
        <div><strong>{identity?.display_name ?? 'Loading identity'}</strong><small>{identity?.username}</small></div>
        <button className="logout" aria-label="Sign out" onClick={() => keycloak.logout({ redirectUri: window.location.origin })}>↗</button></div>
    </aside>
    <section className="workspace"><header><span className="dot" /> Direct LLM <span className="model">Yandex · default</span><span className="phase">PHASE 2</span></header>
      {!active ? <div className="empty-state"><div className="orb"><span /></div><p className="eyebrow">Direct channel ready</p>
        <h1>Welcome, {identity?.display_name ?? 'traveler'}.</h1><p>Create a conversation to begin a persistent, streamed chat.</p>
        <button className="primary" onClick={() => createConversation().catch((reason) => setError(reason.message))}>Start a conversation</button></div>
      : <><div className="messages"><div className="conversation-heading"><small>DIRECT LLM</small><h1>{active.title}</h1></div>
          {(active.messages ?? []).map((message) => <article className={message.role} key={message.id}><label>{message.role}</label><p>{message.content}</p>{message.status !== 'complete' && <small>{message.status}</small>}</article>)}
          {streamText && <article className="assistant streaming"><label>assistant</label><p>{streamText}</p></article>}
          {error && <div className="error">{error}</div>}</div>
        <form className="composer" onSubmit={submit}><textarea aria-label="Message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Message the Yandex model…" disabled={Boolean(busy)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
          {busy ? <button type="button" className="cancel" onClick={() => cancel().catch((reason) => setError(reason.message))}>Stop</button> : <button type="submit" disabled={!draft.trim()}>Send ↗</button>}<small>Responses stream through Bifrost and persist locally.</small></form></>}
    </section>
  </main>
}
