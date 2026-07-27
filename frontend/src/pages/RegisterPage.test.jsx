import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import RegisterPage from './RegisterPage'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../api/client', () => ({
  api: { auth: { register: vi.fn(), providers: vi.fn() } },
}))

function renderRegister({ user = null, loading = false } = {}) {
  useAuth.mockReturnValue({ user, loading })
  render(
    <MemoryRouter initialEntries={['/register']}>
      <Routes>
        <Route path="/" element={<div>QUESTION BANK HOME</div>} />
        <Route path="/login" element={<div>SIGN IN PAGE</div>} />
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
    </MemoryRouter>
  )
}

async function fillForm({ first = 'Ada', last = 'Lovelace', confirm = 'Secure123!' } = {}) {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('First name'), first)
  await user.type(screen.getByLabelText('Last name'), last)
  await user.type(screen.getByLabelText('Email'), 'ada@example.com')
  await user.type(screen.getByLabelText('Password'), 'Secure123!')
  await user.type(screen.getByLabelText('Confirm password'), confirm)
  await user.click(screen.getByRole('button', { name: 'Create account' }))
}

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.auth.providers.mockResolvedValue({ google: false })
  })

  it('submits the name fields along with the credentials', async () => {
    api.auth.register.mockResolvedValue({ id: 1 })
    renderRegister()
    await fillForm()

    await waitFor(() => expect(api.auth.register).toHaveBeenCalledWith({
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
      password: 'Secure123!',
    }))
  })

  it('sends the user to sign in after a successful registration', async () => {
    api.auth.register.mockResolvedValue({ id: 1 })
    renderRegister()
    await fillForm()
    expect(await screen.findByText('SIGN IN PAGE')).toBeInTheDocument()
  })

  it('requires both name fields', () => {
    renderRegister()
    expect(screen.getByLabelText('First name')).toBeRequired()
    expect(screen.getByLabelText('Last name')).toBeRequired()
  })

  it('blocks submission when the passwords do not match', async () => {
    renderRegister()
    await fillForm({ confirm: 'Different123!' })
    expect(api.auth.register).not.toHaveBeenCalled()
    expect(screen.getByText('Passwords do not match.')).toBeInTheDocument()
  })

  it('shows the server error when registration fails', async () => {
    api.auth.register.mockRejectedValue({ status: 409, message: 'Email already registered' })
    renderRegister()
    await fillForm()
    expect(await screen.findByText('Email already registered')).toBeInTheDocument()
  })

  it('redirects already-authenticated users to the question bank', () => {
    renderRegister({ user: { email: 'ada@example.com', role: 'public' } })
    expect(screen.getByText('QUESTION BANK HOME')).toBeInTheDocument()
  })

  it('offers Google sign-up when the backend reports it configured', async () => {
    api.auth.providers.mockResolvedValue({ google: true })
    renderRegister()
    const link = await screen.findByRole('link', { name: /Sign up with Google/ })
    expect(link).toHaveAttribute('href', '/api/auth/google/login')
  })

  it('hides Google sign-up when it is not configured', async () => {
    renderRegister()
    await screen.findByRole('button', { name: 'Create account' })
    expect(screen.queryByRole('link', { name: /Google/ })).not.toBeInTheDocument()
  })
})
