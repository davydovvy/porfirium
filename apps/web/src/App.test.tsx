import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App, loadAgentCatalog } from './App'
import { apiFetch, keycloak } from './auth'

vi.mock('./auth', () => ({
  keycloak: { login: vi.fn(), logout: vi.fn() },
  apiFetch: vi.fn(),
}))

describe('App', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
    window.history.replaceState({}, '', '/')
  })

  it('offers sign in to an unauthenticated visitor', () => {
    render(<App authenticated={false} />)
    expect(screen.getByText('PORFIRIUM')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in with keycloak/i })).toBeInTheDocument()
  })

  it('signs out with a Keycloak-allowed portal redirect URI', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (path === '/api/v1/me') {
        return new Response(JSON.stringify({
          id: 'user-1', username: 'alice', display_name: 'Alice', roles: [],
        }), { status: 200 })
      }
      if (path === '/api/v1/agents' || path === '/api/v1/conversations') {
        return new Response('[]', { status: 200 })
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App authenticated />)
    fireEvent.click(await screen.findByRole('button', { name: /sign out/i }))

    expect(keycloak.logout).toHaveBeenCalledWith({
      redirectUri: `${window.location.origin}/`,
    })
  })

  it('uses target Registry defaults without requesting legacy version routes', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      const body = path === '/api/v1/agents' ? [
        { agent_id: 'agent-id', name: 'Tool Assistant', description: 'demo', default_release_id: 'release-id' },
      ] : []
      return new Response(JSON.stringify(body), { status: 200 })
    })

    const catalog = await loadAgentCatalog()

    expect(catalog.defaultReleaseId).toBe('release-id')
    expect(catalog.agents.map((agent) => agent.name)).toEqual(['Tool Assistant'])
    expect(apiFetch).toHaveBeenCalledTimes(1)
  })

  it('creates a conversation with the user-selected agent release', async () => {
    let selectedRelease = ''
    vi.mocked(apiFetch).mockImplementation(async (path, init) => {
      if (path === '/api/v1/me') {
        return new Response(JSON.stringify({
          id: 'user-1', username: 'alice', display_name: 'Alice', roles: [],
        }), { status: 200 })
      }
      if (path === '/api/v1/agents') {
        return new Response(JSON.stringify([
          { agent_id: 'model-only', name: 'Model-only Assistant', description: '', default_release_id: 'release-model' },
          { agent_id: 'planning-assistant', name: 'Planning Assistant', description: '', default_release_id: 'release-planning' },
        ]), { status: 200 })
      }
      if (path === '/api/v1/conversations' && init?.method === 'POST') {
        selectedRelease = JSON.parse(String(init.body)).release_id
        return new Response(JSON.stringify({
          conversation_id: 'conversation-1', title: 'New conversation', release_id: selectedRelease,
        }), { status: 200 })
      }
      if (path === '/api/v1/conversations') return new Response('[]', { status: 200 })
      if (path.endsWith('/events')) return new Response('', { status: 200 })
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App authenticated />)
    const selector = await screen.findByRole('combobox', { name: 'Agent release' })
    fireEvent.change(selector, { target: { value: 'release-planning' } })
    fireEvent.click(screen.getByRole('button', { name: /new conversation/i }))

    await waitFor(() => expect(selectedRelease).toBe('release-planning'))
    expect(screen.getByText('Isolated · Planning Assistant')).toBeInTheDocument()
  })

  it('clears the running state from the authoritative projection after cancellation', async () => {
    let cancelled = false
    const conversation = {
      conversation_id: 'conversation-1', title: 'Running', release_id: 'release-model',
      messages: [{ message_id: 'message-1', run_id: 'run-1', role: 'user', content: 'Hello', status: 'completed' }],
      input_requests: [], last_sequence: 1,
    }
    vi.mocked(apiFetch).mockImplementation(async (path, init) => {
      if (path === '/api/v1/me') {
        return new Response(JSON.stringify({
          id: 'user-1', username: 'alice', display_name: 'Alice', roles: [],
        }), { status: 200 })
      }
      if (path === '/api/v1/agents') {
        return new Response(JSON.stringify([
          { agent_id: 'model-only', name: 'Model-only Assistant', description: '', default_release_id: 'release-model' },
        ]), { status: 200 })
      }
      if (path === '/api/v1/conversations') {
        return new Response(JSON.stringify([conversation]), { status: 200 })
      }
      if (path === '/api/v1/conversations/conversation-1') {
        return new Response(JSON.stringify({
          ...conversation, active_run: cancelled ? undefined : { run_id: 'run-1', state: 'running' },
        }), { status: 200 })
      }
      if (path.endsWith('/events')) return new Response('', { status: 200 })
      if (path.endsWith('/runs/run-1:cancel') && init?.method === 'POST') {
        cancelled = true
        return new Response(JSON.stringify({ run_id: 'run-1', state: 'cancelled' }), { status: 200 })
      }
      throw new Error(`Unexpected request: ${path}`)
    })

    render(<App authenticated />)
    fireEvent.click(await screen.findByRole('button', { name: 'Stop' }))

    await waitFor(() => expect(cancelled).toBe(true))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument())
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled()
  })
})
