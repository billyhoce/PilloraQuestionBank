import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NavBar from './NavBar'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

vi.mock('../api/client', () => ({ api: { schoolLevels: { list: vi.fn() } } }))
vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

const SECONDARY = { id: 1, name: 'Secondary' }
const PRIMARY = { id: 2, name: 'Primary' }

function renderNavBar(user) {
  useAuth.mockReturnValue({ user, loading: false, login: vi.fn(), logout: vi.fn() })
  render(
    <MemoryRouter>
      <NavBar />
    </MemoryRouter>
  )
}

beforeEach(() => {
  // Cleared here rather than only in afterEach: an unawaited effect from the
  // previous test can land after that hook, and the upsell tests assert on the
  // call count.
  vi.clearAllMocks()
  api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
})
afterEach(() => vi.clearAllMocks())

describe('NavBar links by role', () => {
  it('shows the full menu to admins at all times', () => {
    renderNavBar({ email: 'admin@example.com', role: 'admin' })
    expect(screen.getByRole('link', { name: 'Question Bank' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Generate Paper' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Reference' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Import' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Papers' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Generation Config' })).toBeInTheDocument()
  })

  it('shows only Question Bank and Generate Paper to public users', () => {
    renderNavBar({ email: 'user@example.com', role: 'public' })
    expect(screen.getByRole('link', { name: 'Question Bank' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Generate Paper' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Reference' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Import' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Papers' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Generation Config' })).not.toBeInTheDocument()
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

describe('NavBar Go Premium upsell', () => {
  const goPremium = () => screen.queryByRole('link', { name: /go premium/i })

  it('offers it to a user holding no premium at all', () => {
    renderNavBar({ email: 'user@example.com', role: 'public', premium_school_levels: [] })
    // No wait: holding nothing is incomplete whatever the school level count is.
    expect(goPremium()).toBeInTheDocument()
  })

  it('offers it to a partially-subscribed user', async () => {
    renderNavBar({
      email: 'user@example.com',
      role: 'public',
      premium_school_levels: [SECONDARY],
    })
    expect(await screen.findByRole('link', { name: /go premium/i })).toBeInTheDocument()
  })

  it('hides it once the user holds every school level', async () => {
    renderNavBar({
      email: 'user@example.com',
      role: 'public',
      premium_school_levels: [SECONDARY, PRIMARY],
    })
    await vi.waitFor(() => expect(api.schoolLevels.list).toHaveBeenCalled())
    expect(goPremium()).not.toBeInTheDocument()
  })

  it('hides it from admins, and does not fetch school levels for them', () => {
    renderNavBar({ email: 'admin@example.com', role: 'admin', premium_school_levels: [] })
    expect(goPremium()).not.toBeInTheDocument()
    expect(api.schoolLevels.list).not.toHaveBeenCalled()
  })

  it('hides it when signed out', () => {
    renderNavBar(null)
    expect(goPremium()).not.toBeInTheDocument()
    expect(api.schoolLevels.list).not.toHaveBeenCalled()
  })

  it('stays quiet for a partial subscriber when the school level fetch fails', async () => {
    api.schoolLevels.list.mockRejectedValue(new Error('offline'))
    renderNavBar({
      email: 'user@example.com',
      role: 'public',
      premium_school_levels: [SECONDARY],
    })
    await vi.waitFor(() => expect(api.schoolLevels.list).toHaveBeenCalled())
    expect(goPremium()).not.toBeInTheDocument()
  })
})
