import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, keycloak } from './auth'

type Identity = { id: string; username: string; display_name: string; roles: string[] }
type Mode = 'direct' | 'agent'
type Conversation = { id: string; title: string; mode: Mode; agent_version_id?: string | null; messages?: Message[]; active_turn?: Turn | null }
type Agent = { id: string; slug: string; name: string; description: string; version: { id: string; version: string; digest: string } }
type Message = { id: string; turn_id?: string; role: 'user' | 'assistant'; content: string; status: string }
type Turn = { turn_id: string; state: string; events_url: string; correlation_id: string }
type StreamEvent = { sequence: number; type: string; payload: Record<string, string> }
type Capabilities = { agent_execution: { mode: string; enabled: boolean; code?: string; message?: string } }

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: `Request failed (${response.status})` }))
    const detail = body.detail
    throw new Error(typeof detail === 'object' && detail?.message ? detail.message : detail ?? `Request failed (${response.status})`)
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
  const [progress, setProgress] = useState<string[]>([])
  const [newMode, setNewMode] = useState<Mode>('direct')
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentVersion, setSelectedAgentVersion] = useState('')
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
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
    setProgress([])
    setError(null)
    const item = await json<Conversation>(`/api/v1/conversations/${id}`)
    setActive(item)
    setNewMode(item.mode)
    window.history.replaceState({}, '', `/chat/${id}`)
  }, [])

  useEffect(() => {
    if (!authenticated) return
    Promise.all([json<Identity>('/api/v1/me'), loadConversations(), json<Agent[]>('/api/v1/agents'), json<Capabilities>('/api/v1/capabilities')])
      .then(([me, items, catalog, available]) => {
        setIdentity(me)
        setAgents(catalog)
        setCapabilities(available)
        setSelectedAgentVersion(catalog[0]?.version.id ?? '')
        const routeId = window.location.pathname.match(/^\/chat\/([^/]+)$/)?.[1]
        if (routeId) openConversation(routeId).catch((reason: Error) => setError(reason.message))
        else if (items[0]) openConversation(items[0].id).catch((reason: Error) => setError(reason.message))
      })
      .catch((reason: Error) => setError(reason.message))
  }, [authenticated, loadConversations, openConversation])

  async function createConversation(mode: Mode = newMode) {
    const item = await json<Conversation>('/api/v1/conversations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'New conversation', mode,
        agent_version_id: mode === 'agent' ? selectedAgentVersion || undefined : undefined,
      }),
    })
    setConversations((current) => [item, ...current])
    setActive({ ...item, messages: [] })
    setTurn(null)
    setStreamText('')
    setProgress([])
    window.history.replaceState({}, '', `/chat/${item.id}`)
  }

  function selectMode(mode: Mode) {
    setNewMode(mode)
    const next = conversations.find((item) => item.mode === mode)
    if (next) {
      openConversation(next.id).catch((reason: Error) => setError(reason.message))
    } else {
      streamAbort.current?.abort()
      setActive(null)
      setTurn(null)
      setStreamText('')
      setProgress([])
      setError(null)
      window.history.replaceState({}, '', '/')
    }
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
        if (event.type === 'agent.status') setProgress((value) => [...value, event.payload.label])
        if (event.type.startsWith('tool.')) setProgress((value) => [...value, event.payload.label])
        if (event.type === 'turn.failed') setError(`${event.payload.message} Reference: ${event.payload.correlation_id}`)
        if (['turn.completed', 'turn.failed', 'turn.cancelled'].includes(event.type)) {
          setTurn((current) => current ? { ...current, state: event.type.slice(5) } : current)
        }
      }
    }
    await openConversation(conversationId)
    await loadConversations()
  }

  useEffect(() => {
    if (!active?.active_turn || turn) return
    const resumed = active.active_turn
    setTurn(resumed)
    consumeEvents(resumed, active.id).catch((reason: Error) => {
      if (reason.name !== 'AbortError') setError(reason.message)
    })
  // consumeEvents intentionally follows the selected conversation only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, active?.active_turn?.turn_id])

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
    <main className="landing"><nav><span className="brand">PORFIRIUM</span><span className="status">Phase 4</span></nav>
      <section className="hero"><p className="eyebrow">A durable, observable AI workspace</p>
        <h1>One place to talk,<br /><em>build, and inspect.</em></h1>
        <p className="lede">Run direct conversations or durable agents through your private, local-first workspace.</p>
        <button onClick={() => keycloak.login()}>Sign in with Keycloak <span>↗</span></button></section>
      <footer><span>Identity protected</span><span>Temporal durable</span><span>Phase 4 / 5</span></footer></main>
  )

  const busy = turn && ['accepted', 'running'].includes(turn.state)
  const agentAvailable = capabilities?.agent_execution.enabled ?? false
  return <main className="app-shell">
    <aside><div className="brand">PORFIRIUM</div>
      <div className="mode-picker" aria-label="New conversation mode">
        <button className={newMode === 'direct' ? 'active' : ''} onClick={() => selectMode('direct')}>Direct</button>
        <button className={newMode === 'agent' ? 'active' : ''} onClick={() => selectMode('agent')}>Agent</button>
      </div>
      <button className="new-chat" onClick={() => createConversation().catch((reason) => setError(reason.message))}>＋ New {newMode} conversation</button>
      {newMode === 'agent' && <label className="agent-selector">Agent version
        <select aria-label="Agent version" value={selectedAgentVersion} onChange={(event) => setSelectedAgentVersion(event.target.value)}>
          {agents.map((agent) => <option key={agent.version.id} value={agent.version.id}>{agent.name} · {agent.version.version}</option>)}
        </select>
      </label>}
      <div className="conversation-list">{conversations.filter((item) => item.mode === newMode).map((item) =>
        <button className={active?.id === item.id ? 'selected' : ''} key={item.id} onClick={() => openConversation(item.id).catch((reason) => setError(reason.message))}>{item.title}</button>)}</div>
      <div className="profile"><div className="avatar">{identity?.display_name?.[0] ?? '…'}</div>
        <div><strong>{identity?.display_name ?? 'Loading identity'}</strong><small>{identity?.username}</small></div>
        <button className="logout" aria-label="Sign out" onClick={() => keycloak.logout({ redirectUri: window.location.origin })}>↗</button></div>
    </aside>
    <section className="workspace"><header><span className="dot" /> {active?.mode === 'agent' ? 'Agent' : 'Direct LLM'} <span className="model">{active?.mode === 'agent' ? `Temporal · ${agents.find((agent) => agent.version.id === active.agent_version_id)?.name ?? 'Tool Agent'} ${agents.find((agent) => agent.version.id === active.agent_version_id)?.version.version ?? 'v1'}` : 'Yandex · default'}</span><span className="phase">INCREMENT 6</span></header>
      {!active ? <div className="empty-state"><div className="orb"><span /></div><p className="eyebrow">Direct channel ready</p>
        <h1>Welcome, {identity?.display_name ?? 'traveler'}.</h1><p>Create a direct conversation or a durable Agent run.</p>
        <button className="primary" onClick={() => createConversation().catch((reason) => setError(reason.message))}>Start a conversation</button></div>
      : <><div className="messages"><div className="conversation-heading"><small>{active.mode === 'agent' ? 'DURABLE AGENT' : 'DIRECT LLM'}</small><h1>{active.title}</h1></div>
          {(active.messages ?? []).map((message) => <article className={message.role} key={message.id}><label>{message.role}</label><p>{message.content}</p>{message.status !== 'complete' && <small>{message.status}</small>}</article>)}
          {streamText && <article className="assistant streaming"><label>assistant</label><p>{streamText}</p></article>}
          {busy && active.mode === 'agent' && <div className="agent-progress"><small>WORKFLOW PROGRESS</small>{progress.length ? progress.map((item, index) => <p key={`${item}-${index}`}>✓ {item}</p>) : <p>○ Waiting for worker</p>}</div>}
          {error && <div className="error">{error}</div>}</div>
        <form className="composer" onSubmit={submit}><textarea aria-label="Message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={active.mode === 'agent' && !agentAvailable ? 'Agent runtime maintenance in progress…' : active.mode === 'agent' ? 'Give the durable agent a task…' : 'Message the Yandex model…'} disabled={Boolean(busy) || active.mode === 'agent' && !agentAvailable} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
          {busy ? <button type="button" className="cancel" onClick={() => cancel().catch((reason) => setError(reason.message))}>Stop</button> : <button type="submit" disabled={!draft.trim() || active.mode === 'agent' && !agentAvailable}>Send ↗</button>}<small>{active.mode === 'agent' && !agentAvailable ? capabilities?.agent_execution.message ?? 'Agent execution is temporarily unavailable while the runtime is upgraded.' : active.mode === 'agent' ? 'Temporal preserves this run across worker restarts.' : 'Responses stream through Agentgateway and persist locally.'}</small></form></>}
    </section>
  </main>
}
