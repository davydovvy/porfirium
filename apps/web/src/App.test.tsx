import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App, loadAgentCatalog } from './App'
import { apiFetch } from './auth'
import { progressLabel, terminalTurnError } from './progress'

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

  it('provides readable progress for legacy events without labels', () => {
    expect(progressLabel({ sequence: 1, type: 'tool.requested', payload: { tool: 'demo-time' } })).toBe('Requested demo-time')
    expect(progressLabel({ sequence: 2, type: 'agent.status', payload: { status: 'synthesizing' } })).toBe('synthesizing')
  })

  it('keeps the latest terminal failure visible after refresh', () => {
    expect(terminalTurnError({ state: 'failed', correlation_id: 'abc123' })).toContain('abc123')
    expect(terminalTurnError({ state: 'completed', correlation_id: 'abc123' })).toBeNull()
  })

  it('expands every published version while retaining the server default', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      const body = path === '/api/v1/agents'
        ? [{ id: 'agent-id', slug: 'tool-assistant', name: 'Tool Assistant', description: 'demo', version: { id: 'v12', version: '1.2.0', digest: 'old' } }]
        : [
            { id: 'v13', version: '1.3.0', digest: 'new' },
            { id: 'v12', version: '1.2.0', digest: 'old' },
          ]
      return new Response(JSON.stringify(body), { status: 200 })
    })

    const catalog = await loadAgentCatalog()

    expect(catalog.defaultVersionId).toBe('v12')
    expect(catalog.agents.map((agent) => agent.version.version)).toEqual(['1.3.0', '1.2.0'])
  })
})
