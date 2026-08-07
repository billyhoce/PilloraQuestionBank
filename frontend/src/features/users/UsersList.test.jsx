import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UsersList from './UsersList'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'

vi.mock('../../api/client', () => ({
  api: {
    users: { list: vi.fn(), updateRole: vi.fn(), setPremiumSchoolLevels: vi.fn() },
    schoolLevels: { list: vi.fn() },
  },
}))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))

const SECONDARY = { id: 1, name: 'Secondary' }
const PRIMARY = { id: 2, name: 'Primary' }

const users = [
  { id: 1, email: 'admin@test.com', first_name: 'Al', last_name: 'Min', role: 'admin', premium_school_levels: [], created_at: '2026-01-01T00:00:00Z' },
  { id: 2, email: 'user@test.com', first_name: 'Ada', last_name: 'Lovelace', role: 'public', premium_school_levels: [SECONDARY], created_at: '2026-01-02T00:00:00Z' },
  // Predates the name fields — the table must still render the row.
  { id: 3, email: 'legacy@test.com', first_name: '', last_name: '', role: 'public', premium_school_levels: [], created_at: '2026-01-03T00:00:00Z' },
]

describe('UsersList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    api.users.list.mockResolvedValue(users)
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
    api.users.updateRole.mockResolvedValue({ id: 2, email: 'user@test.com', role: 'admin' })
    api.users.setPremiumSchoolLevels.mockResolvedValue({ id: 2, premium_school_levels: [] })
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
    await user.selectOptions(select, 'admin')

    await waitFor(() => expect(api.users.updateRole).toHaveBeenCalledWith(2, 'admin'))
  })

  it('offers only Normal and Admin — premium is not a role', async () => {
    render(<UsersList />)
    await screen.findByText('user@test.com')
    const options = [...screen.getByLabelText('Tier for user@test.com').options]
    expect(options.map((o) => o.value)).toEqual(['public', 'admin'])
  })

  it('disables the tier control for the current admin (own row)', async () => {
    render(<UsersList />)
    await screen.findByText('admin@test.com')
    expect(screen.getByLabelText('Tier for admin@test.com')).toBeDisabled()
    expect(screen.getByLabelText('Tier for user@test.com')).not.toBeDisabled()
  })

  it('shows a premium checkbox per school level, ticked for the levels held', async () => {
    render(<UsersList />)
    await screen.findByText('user@test.com')
    expect(screen.getByLabelText('Secondary premium for user@test.com')).toBeChecked()
    expect(screen.getByLabelText('Primary premium for user@test.com')).not.toBeChecked()
    expect(screen.getByLabelText('Secondary premium for legacy@test.com')).not.toBeChecked()
  })

  it('sends the whole resulting set when granting a level', async () => {
    const user = userEvent.setup()
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByLabelText('Primary premium for user@test.com'))

    // Replace, not merge: the existing Secondary grant has to be sent too.
    await waitFor(() =>
      expect(api.users.setPremiumSchoolLevels).toHaveBeenCalledWith(2, [1, 2])
    )
  })

  it('sends the remaining set when revoking a level', async () => {
    const user = userEvent.setup()
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByLabelText('Secondary premium for user@test.com'))

    await waitFor(() =>
      expect(api.users.setPremiumSchoolLevels).toHaveBeenCalledWith(2, [])
    )
  })

  it('reverts and reports the error when a grant fails', async () => {
    const user = userEvent.setup()
    api.users.setPremiumSchoolLevels.mockRejectedValue(new Error('nope'))
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByLabelText('Primary premium for user@test.com'))

    expect(await screen.findByText('nope')).toBeInTheDocument()
    expect(screen.getByLabelText('Primary premium for user@test.com')).not.toBeChecked()
  })

  it('shows admins as having all access rather than checkboxes', async () => {
    render(<UsersList />)
    await screen.findByText('admin@test.com')
    expect(screen.getByText('All access')).toBeInTheDocument()
    expect(screen.queryByLabelText('Secondary premium for admin@test.com')).not.toBeInTheDocument()
  })
})
