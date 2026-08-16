import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from './App'

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
})
