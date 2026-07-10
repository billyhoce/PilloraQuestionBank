import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import LoginPage from './LoginPage'
import { useAuth } from '../context/AuthContext'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

const login = vi.fn()

function renderLogin({ user = null, loading = false } = {}) {
  useAuth.mockReturnValue({ user, loading, login })
  render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/" element={<div>QUESTION BANK HOME</div>} />
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </MemoryRouter>
  )
}

async function submitLogin() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'someone@example.com')
  await user.type(screen.getByLabelText('Password'), 'secret123')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('LoginPage redirects', () => {
  beforeEach(() => vi.clearAllMocks())

  it('redirects public users to the question bank after login', async () => {
    login.mockResolvedValue({ email: 'someone@example.com', role: 'public' })
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('QUESTION BANK HOME')).toBeInTheDocument()
  })

  it('redirects admins to the question bank after login', async () => {
    login.mockResolvedValue({ email: 'admin@example.com', role: 'admin' })
    renderLogin()
    await submitLogin()
    expect(await screen.findByText('QUESTION BANK HOME')).toBeInTheDocument()
  })

  it('redirects already-authenticated users to the question bank', () => {
    renderLogin({ user: { email: 'someone@example.com', role: 'public' } })
    expect(screen.getByText('QUESTION BANK HOME')).toBeInTheDocument()
  })
})
