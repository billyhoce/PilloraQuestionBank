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
  { id: 1, email: 'admin@test.com', role: 'admin', created_at: '2026-01-01T00:00:00Z' },
  { id: 2, email: 'user@test.com', role: 'public', created_at: '2026-01-02T00:00:00Z' },
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
