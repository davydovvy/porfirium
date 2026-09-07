import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App, loadAgentCatalog } from './App'
import { apiFetch } from './auth'

vi.mock('./auth', () => ({
  keycloak: { login: vi.fn(), logout: vi.fn() },
  apiFetch: vi.fn(),
}))

describe('App', () => {
  it('offers sign in to an unauthenticated visitor', () => {
    render(<App authenticated={false} />)
    expect(screen.getByText('PORFIRIUM')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in with keycloak/i })).toBeInTheDocument()
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
})
