import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import SubscribePage from './SubscribePage'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

vi.mock('../api/client', () => ({ api: { schoolLevels: { list: vi.fn() } } }))
vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

const SECONDARY = { id: 1, name: 'Secondary' }
const PRIMARY = { id: 2, name: 'Primary' }

const renderAt = (path = '/subscribe') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <SubscribePage />
    </MemoryRouter>
  )

describe('SubscribePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
  })

  it('renders one plan per school level for a user with no premium', async () => {
    useAuth.mockReturnValue({ user: { id: 2, role: 'public', premium_school_levels: [] } })
    renderAt()

    expect(await screen.findByText('Secondary Premium')).toBeInTheDocument()
    expect(screen.getByText('Primary Premium')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Subscribe to Secondary' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Subscribe to Primary' })).toBeDisabled()
  })

  it('marks only the plans the user already holds as owned', async () => {
    useAuth.mockReturnValue({
      user: { id: 2, role: 'public', premium_school_levels: [SECONDARY] },
    })
    renderAt()

    expect(await screen.findByText(/already have Secondary access/i)).toBeInTheDocument()
    // The plan they don't hold is still on offer.
    expect(screen.getByRole('button', { name: 'Subscribe to Primary' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Subscribe to Secondary' })).not.toBeInTheDocument()
  })

  it('treats an admin as holding every plan', async () => {
    useAuth.mockReturnValue({ user: { id: 1, role: 'admin', premium_school_levels: [] } })
    renderAt()

    expect(await screen.findByText(/already have Secondary access/i)).toBeInTheDocument()
    expect(screen.getByText(/already have Primary access/i)).toBeInTheDocument()
  })

  it('highlights the plan named by ?school_level', async () => {
    useAuth.mockReturnValue({ user: { id: 2, role: 'public', premium_school_levels: [] } })
    renderAt('/subscribe?school_level=Primary')

    await screen.findByText('Primary Premium')
    expect(screen.getByText(/plan the question you opened needs/i)).toBeInTheDocument()
    expect(screen.getByTestId('plan-Primary').className).toMatch(/border-amber-400/)
    expect(screen.getByTestId('plan-Secondary').className).not.toMatch(/border-amber-400/)
  })

  it('highlights nothing without the query param', async () => {
    useAuth.mockReturnValue({ user: { id: 2, role: 'public', premium_school_levels: [] } })
    renderAt()

    await screen.findByText('Primary Premium')
    expect(screen.queryByText(/plan the question you opened needs/i)).not.toBeInTheDocument()
  })
})
