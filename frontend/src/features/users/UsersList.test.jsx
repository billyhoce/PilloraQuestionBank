import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UsersList from './UsersList'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

vi.mock('../../api/client', () => ({
  api: { users: { list: vi.fn(), updateRole: vi.fn() } },
}))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))

const users = [
  { id: 1, email: 'admin@test.com', first_name: 'Al', last_name: 'Min', role: 'admin', created_at: '2026-01-01T00:00:00Z' },
  { id: 2, email: 'user@test.com', first_name: 'Ada', last_name: 'Lovelace', role: 'public', created_at: '2026-01-02T00:00:00Z' },
  // Predates the name fields — the table must still render the row.
  { id: 3, email: 'legacy@test.com', first_name: '', last_name: '', role: 'premium', created_at: '2026-01-03T00:00:00Z' },
]

describe('UsersList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    api.users.list.mockResolvedValue(users)
    api.users.updateRole.mockResolvedValue({ id: 2, email: 'user@test.com', role: 'premium' })
  })

  it('lists users with their email', async () => {
    render(<UsersList />)
    expect(await screen.findByText('user@test.com')).toBeInTheDocument()
    expect(screen.getByText('admin@test.com')).toBeInTheDocument()
  })

  it('lists users with their name', async () => {
    render(<UsersList />)
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('Al Min')).toBeInTheDocument()
  })

  it('shows a dash for accounts with no name on file', async () => {
    render(<UsersList />)
    await screen.findByText('legacy@test.com')
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('calls updateRole when a tier is changed', async () => {
    const user = userEvent.setup()
    render(<UsersList />)
    await screen.findByText('user@test.com')

    const select = screen.getByLabelText('Tier for user@test.com')
    await user.selectOptions(select, 'premium')

    await waitFor(() => expect(api.users.updateRole).toHaveBeenCalledWith(2, 'premium'))
  })

  it('disables the tier control for the current admin (own row)', async () => {
    render(<UsersList />)
    await screen.findByText('admin@test.com')
    expect(screen.getByLabelText('Tier for admin@test.com')).toBeDisabled()
    expect(screen.getByLabelText('Tier for user@test.com')).not.toBeDisabled()
  })
})
