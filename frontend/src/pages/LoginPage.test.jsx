import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import LoginPage from './LoginPage'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../api/client', () => ({
  api: { auth: { providers: vi.fn() } },
}))

const login = vi.fn()

function renderLogin({ user = null, loading = false, entry = '/login' } = {}) {
  useAuth.mockReturnValue({ user, loading, login })
  render(
    <MemoryRouter initialEntries={[entry]}>
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
  beforeEach(() => {
    vi.clearAllMocks()
    api.auth.providers.mockResolvedValue({ google: false })
  })

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

describe('LoginPage Google sign-in', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the Google button when the backend reports it configured', async () => {
    api.auth.providers.mockResolvedValue({ google: true })
    renderLogin()
    const link = await screen.findByRole('link', { name: /Sign in with Google/ })
    // A real navigation, not client-side routing — the backend has to set the
    // state cookie and redirect on to Google.
    expect(link).toHaveAttribute('href', '/api/auth/google/login')
  })

  it('hides the Google button when it is not configured', async () => {
    api.auth.providers.mockResolvedValue({ google: false })
    renderLogin()
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByRole('link', { name: /Google/ })).not.toBeInTheDocument()
  })

  it('hides the Google button when the providers lookup fails', async () => {
    api.auth.providers.mockRejectedValue({ status: 500, message: 'boom' })
    renderLogin()
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByRole('link', { name: /Google/ })).not.toBeInTheDocument()
  })

  it('surfaces a failed Google sign-in from the ?error= redirect', async () => {
    api.auth.providers.mockResolvedValue({ google: true })
    renderLogin({ entry: '/login?error=google_email_unverified' })
    expect(
      await screen.findByText('Your Google email address is not verified.')
    ).toBeInTheDocument()
  })

  it('ignores an unrecognised error code rather than echoing it', async () => {
    api.auth.providers.mockResolvedValue({ google: false })
    renderLogin({ entry: '/login?error=something_else' })
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByText(/something_else/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Google/)).not.toBeInTheDocument()
  })
})
