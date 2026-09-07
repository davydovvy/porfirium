import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { AgentBuilder } from './AgentBuilder'
import { apiFetch, keycloak } from './auth'

type Identity = { id: string; username: string; display_name: string; roles: string[]; capabilities?: { agent_authoring?: boolean; agent_publication?: boolean } }
type Agent = { agent_id: string; name: string; description: string; default_release_id: string | null }
type Message = { message_id: string; run_id: string; role: 'user' | 'assistant'; content: string; status: string }
type InputRequest = { input_request_id: string; run_id: string; prompt: string; state: string }
type ActiveRun = { run_id: string; state: string }
type Conversation = { conversation_id: string; title: string; release_id: string; messages?: Message[]; input_requests?: InputRequest[]; last_sequence?: number; active_run?: ActiveRun }

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: `Request failed (${response.status})` }))
    const detail = body.detail ?? body.title
    throw new Error(typeof detail === 'object' && detail?.message ? detail.message : detail ?? `Request failed (${response.status})`)
  }
  return response.json()
}

function command(content?: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() }, body: content === undefined ? undefined : JSON.stringify(content) }
}

// eslint-disable-next-line react-refresh/only-export-components
export async function loadAgentCatalog(): Promise<{ agents: Agent[]; defaultReleaseId: string }> {
  const agents = await json<Agent[]>('/api/v1/agents')
  return { agents, defaultReleaseId: agents.find((agent) => agent.default_release_id)?.default_release_id ?? '' }
}

export function App({ authenticated }: { authenticated: boolean }) {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [releaseId, setReleaseId] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [draft, setDraft] = useState('')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [streamText, setStreamText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'chat' | 'authoring'>('chat')
  const streamAbort = useRef<AbortController | null>(null)

  const loadConversations = useCallback(async () => {
    const items = await json<Conversation[]>('/api/v1/conversations')
    setConversations(items)
    return items
  }, [])

  const openConversation = useCallback(async (id: string) => {
    streamAbort.current?.abort()
    setActiveRunId(null)
    setStreamText('')
    setError(null)
    const item = await json<Conversation>(`/api/v1/conversations/${id}`)
    setActive(item)
    setActiveRunId(item.active_run?.run_id ?? null)
    window.history.replaceState({}, '', `/chat/${id}`)
  }, [])

  useEffect(() => {
    if (!authenticated) return
    Promise.all([json<Identity>('/api/v1/me'), loadConversations(), loadAgentCatalog()])
      .then(([me, items, catalog]) => {
        setIdentity(me)
        setAgents(catalog.agents)
        setReleaseId(catalog.defaultReleaseId)
        const routeId = window.location.pathname.match(/^\/chat\/([^/]+)$/)?.[1]
        if (routeId) openConversation(routeId).catch((reason: Error) => setError(reason.message))
        else if (items[0]) openConversation(items[0].conversation_id).catch((reason: Error) => setError(reason.message))
      })
      .catch((reason: Error) => setError(reason.message))
  }, [authenticated, loadConversations, openConversation])

  useEffect(() => {
    if (!active) return
    consumeEvents(active.conversation_id, active.last_sequence ?? 0).catch((reason: Error) => {
      if (reason.name !== 'AbortError') setError(reason.message)
    })
  // The selected projection owns the replay cursor; reconnect when it changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.conversation_id, active?.last_sequence])

  async function createConversation() {
    if (!releaseId) throw new Error('Select an agent release first')
    const item = await json<Conversation>('/api/v1/conversations', command({ title: 'New conversation', release_id: releaseId }))
    setConversations((current) => [item, ...current])
    setActive({ ...item, messages: [], input_requests: [], last_sequence: 0 })
    setActiveRunId(null)
    setStreamText('')
    window.history.replaceState({}, '', `/chat/${item.conversation_id}`)
  }

  async function consumeEvents(conversationId: string, after: number) {
    streamAbort.current?.abort()
    const controller = new AbortController()
    streamAbort.current = controller
    const response = await apiFetch(`/api/v1/conversations/${conversationId}/events`, {
      signal: controller.signal, headers: { 'Last-Event-ID': String(after) },
    })
    if (!response.ok || !response.body) throw new Error(`Event stream failed (${response.status})`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) return
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const eventType = frame.split('\n').find((line) => line.startsWith('event: '))?.slice(7)
        const dataLine = frame.split('\n').find((line) => line.startsWith('data: '))
        if (!eventType || !dataLine) continue
        const data = JSON.parse(dataLine.slice(6)) as Record<string, unknown>
        if (eventType === 'porfirium.message.delta.v1') setStreamText((current) => current + String(data.content ?? ''))
        if (['porfirium.message.completed.v1', 'porfirium.message.interrupted.v1', 'porfirium.message.failed.v1'].includes(eventType)) {
          controller.abort()
          setActiveRunId(null)
          await openConversation(conversationId)
          await loadConversations()
          return
        }
        if (eventType === 'input.request_created') {
          controller.abort()
          setActiveRunId(null)
          await openConversation(conversationId)
          return
        }
      }
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || !active || activeRunId) return
    setDraft('')
    setError(null)
    setStreamText('')
    const optimistic: Message = { message_id: crypto.randomUUID(), run_id: '', role: 'user', content, status: 'completed' }
    setActive({ ...active, messages: [...(active.messages ?? []), optimistic] })
    try {
      const created = await json<{ run_id: string; conversation_sequence: number }>(
        `/api/v1/conversations/${active.conversation_id}/messages`, command({ content }),
      )
      setActiveRunId(created.run_id)
      await consumeEvents(active.conversation_id, created.conversation_sequence)
    } catch (reason) {
      if ((reason as Error).name !== 'AbortError') setError((reason as Error).message)
    }
  }

  async function cancel() {
    if (!activeRunId) return
    if (!active) return
    await json(`/api/v1/conversations/${active.conversation_id}/runs/${activeRunId}:cancel`, command())
  }

  async function answerInput(input: InputRequest) {
    const response = window.prompt(input.prompt)
    if (response === null) return
    await json(`/api/v1/input-requests/${input.input_request_id}/responses`, command({ response }))
    if (active) await openConversation(active.conversation_id)
  }

  if (!authenticated) return (
    <main className="landing"><nav><span className="brand">PORFIRIUM</span><span className="status">Target</span></nav>
      <section className="hero"><p className="eyebrow">An isolated agent workspace</p>
        <h1>One place to talk,<br /><em>build, and inspect.</em></h1>
        <p className="lede">Start fresh conversations with immutable, isolated agent releases.</p>
        <button onClick={() => keycloak.login()}>Sign in with Keycloak <span>↗</span></button></section>
      <footer><span>Identity protected</span><span>Container isolated</span><span>Target runtime</span></footer></main>
  )

  const selectedAgent = agents.find((agent) => agent.default_release_id === (active?.release_id ?? releaseId))
  return <main className="app-shell">
    <aside><div className="brand">PORFIRIUM</div>
      <label className="agent-selector">Agent release
        <select aria-label="Agent release" value={releaseId} onChange={(event) => setReleaseId(event.target.value)}>
          {agents.filter((agent) => agent.default_release_id).map((agent) => <option key={agent.agent_id} value={agent.default_release_id ?? ''}>{agent.name}</option>)}
        </select>
      </label>
      <button className="new-chat" onClick={() => createConversation().catch((reason) => setError(reason.message))}>＋ New conversation</button>
      {identity?.capabilities?.agent_authoring && <button className={view === 'authoring' ? 'new-chat selected' : 'new-chat'} onClick={() => setView(view === 'authoring' ? 'chat' : 'authoring')}>{view === 'authoring' ? '← Back to chat' : '◇ Publish agent'}</button>}
      <div className="conversation-list">{conversations.map((item) =>
        <button className={active?.conversation_id === item.conversation_id ? 'selected' : ''} key={item.conversation_id} onClick={() => openConversation(item.conversation_id).catch((reason) => setError(reason.message))}>{item.title}</button>)}</div>
      <div className="profile"><div className="avatar">{identity?.display_name?.[0] ?? '…'}</div>
        <div><strong>{identity?.display_name ?? 'Loading identity'}</strong><small>{identity?.username}</small></div>
        <button className="logout" aria-label="Sign out" onClick={() => keycloak.logout({ redirectUri: window.location.origin })}>↗</button></div>
    </aside>
    {view === 'authoring' ? <AgentBuilder
      canPublish={Boolean(identity?.capabilities?.agent_publication)}
      canAdmin={Boolean(identity?.roles.includes('genai-agent-registry-admin'))}
      onCatalogChanged={() => loadAgentCatalog().then((catalog) => { setAgents(catalog.agents); setReleaseId(catalog.defaultReleaseId) }).catch((reason: Error) => setError(reason.message))}
    /> : <section className="workspace"><header><span className="dot" /> Agent
      <span className="model">Isolated · {selectedAgent?.name ?? 'Select a release'}</span><span className="phase">TARGET</span></header>
      {!active ? <div className="empty-state"><div className="orb"><span /></div><p className="eyebrow">New runtime ready</p>
        <h1>Welcome, {identity?.display_name ?? 'traveler'}.</h1><p>Choose an agent and start a new conversation.</p>
        <button className="primary" disabled={!releaseId} onClick={() => createConversation().catch((reason) => setError(reason.message))}>Start a conversation</button>
        {error && <div className="error">{error}</div>}</div>
      : <><div className="messages"><div className="conversation-heading"><small>ISOLATED AGENT</small><h1>{active.title}</h1></div>
          {(active.messages ?? []).map((message) => <article className={message.role} key={message.message_id}><label>{message.role}</label><p>{message.content}</p>{!['complete', 'completed'].includes(message.status) && <small>{message.status}</small>}</article>)}
          {streamText && <article className="assistant streaming"><label>assistant</label><p>{streamText}</p></article>}
          {(active.input_requests ?? []).filter((input) => input.state === 'pending').map((input) =>
            <div className="agent-progress" key={input.input_request_id}><small>INPUT REQUIRED</small><p>{input.prompt}</p><button onClick={() => answerInput(input).catch((reason) => setError(reason.message))}>Respond</button></div>)}
          {activeRunId && <div className="agent-progress"><small>AGENT RUNNING</small><p>○ Waiting for isolated agent output</p></div>}
          {error && <div className="error">{error}</div>}</div>
        <form className="composer" onSubmit={submit}><textarea aria-label="Message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Give the agent a task…" disabled={Boolean(activeRunId)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
          {activeRunId ? <button type="button" className="cancel" onClick={() => cancel().catch((reason) => setError(reason.message))}>Stop</button> : <button type="submit" disabled={!draft.trim()}>Send ↗</button>}<small>Runs execute in isolated containers and durable output reconnects automatically.</small></form></>}
    </section>}
  </main>
}
