import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NavBar from './NavBar'
import { useAuth } from '../context/AuthContext'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

function renderNavBar(user) {
  useAuth.mockReturnValue({ user, loading: false, login: vi.fn(), logout: vi.fn() })
  render(
    <MemoryRouter>
      <NavBar />
    </MemoryRouter>
  )
}

afterEach(() => vi.clearAllMocks())

describe('NavBar links by role', () => {
  it('shows the full menu to admins at all times', () => {
    renderNavBar({ email: 'admin@example.com', role: 'admin' })
    expect(screen.getByRole('link', { name: 'Question Bank' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Generate Paper' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Reference' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Papers' })).toBeInTheDocument()
  })

  it('shows only Question Bank and Generate Paper to public users', () => {
    renderNavBar({ email: 'user@example.com', role: 'public' })
    expect(screen.getByRole('link', { name: 'Question Bank' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Generate Paper' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reference' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Import' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Papers' })).not.toBeInTheDocument()
  })

  it('shows a Log in link instead of the account button when signed out', () => {
    renderNavBar(null)
    expect(screen.getByRole('link', { name: 'Log in' })).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reference' })).not.toBeInTheDocument()
  })

  it('shows the account button (email) instead of Log in when signed in', () => {
    renderNavBar({ email: 'user@example.com', role: 'public' })
    expect(screen.getByRole('button', { name: /user@example\.com/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Log in' })).not.toBeInTheDocument()
  })
})
