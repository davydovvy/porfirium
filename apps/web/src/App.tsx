import { useEffect, useState } from 'react'
import { apiFetch, keycloak } from './auth'

type Identity = {
  id: string
  username: string
  display_name: string
  email?: string
  roles: string[]
  capabilities: { chat: boolean; agent: boolean; tools: boolean }
}

export function App({ authenticated }: { authenticated: boolean }) {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!authenticated) return
    apiFetch('/api/v1/me')
      .then(async (response) => {
        if (!response.ok) throw new Error(`Identity request failed (${response.status})`)
        setIdentity(await response.json())
      })
      .catch((reason: Error) => setError(reason.message))
  }, [authenticated])

  if (!authenticated) {
    return (
      <main className="landing">
        <nav><span className="brand">PORFIRIUM</span><span className="status">Phase 1</span></nav>
        <section className="hero">
          <p className="eyebrow">A durable, observable AI workspace</p>
          <h1>One place to talk,<br /><em>build, and inspect.</em></h1>
          <p className="lede">The platform skeleton is online. Sign in to enter your isolated workspace.</p>
          <button onClick={() => keycloak.login()}>Sign in with Keycloak <span>↗</span></button>
        </section>
        <footer><span>Identity protected</span><span>Local-first</span><span>Phase 1 / 5</span></footer>
      </main>
    )
  }

  return (
    <main className="app-shell">
      <aside>
        <div className="brand">PORFIRIUM</div>
        <button className="new-chat" disabled>＋ New conversation</button>
        <div className="empty-nav">Conversations arrive in Phase 2.</div>
        <div className="profile">
          <div className="avatar">{identity?.display_name?.[0] ?? '…'}</div>
          <div><strong>{identity?.display_name ?? 'Loading identity'}</strong><small>{identity?.username}</small></div>
          <button className="logout" aria-label="Sign out" onClick={() => keycloak.logout({ redirectUri: window.location.origin })}>↗</button>
        </div>
      </aside>
      <section className="workspace">
        <header><span className="dot" /> Authenticated workspace <span className="phase">PHASE 1</span></header>
        <div className="empty-state">
          <div className="orb"><span /></div>
          <p className="eyebrow">Platform skeleton ready</p>
          <h1>Welcome, {identity?.display_name ?? 'traveler'}.</h1>
          <p>Your identity is verified and your private workspace is ready. Direct LLM conversations unlock in Phase 2.</p>
          {error && <div className="error">{error}</div>}
          <div className="capabilities">
            <span className="active">✓ Identity</span><span>○ Direct chat</span><span>○ Durable agent</span><span>○ MCP tools</span>
          </div>
        </div>
      </section>
    </main>
  )
}
