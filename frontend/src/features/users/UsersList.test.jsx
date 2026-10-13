import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import UsersList from './UsersList'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { useSiteConfig } from '../../context/SiteConfigContext'

vi.mock('../../api/client', () => ({
  api: {
    users: {
      list: vi.fn(),
      create: vi.fn(),
      remove: vi.fn(),
      updateRole: vi.fn(),
      setPremiumSchoolLevels: vi.fn(),
    },
    schoolLevels: { list: vi.fn() },
    siteConfig: { update: vi.fn() },
  },
}))
vi.mock('../../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../../context/SiteConfigContext', () => ({ useSiteConfig: vi.fn() }))

const SECONDARY = { id: 1, name: 'Secondary' }
const PRIMARY = { id: 2, name: 'Primary' }

const users = [
  { id: 1, email: 'admin@test.com', first_name: 'Al', last_name: 'Min', role: 'admin', premium_school_levels: [], created_at: '2026-01-01T00:00:00Z', has_password: true, has_google: false, is_invited: false, last_login_at: '2026-02-01T00:00:00Z', papers_generated: 4 },
  { id: 2, email: 'user@test.com', first_name: 'Ada', last_name: 'Lovelace', role: 'public', premium_school_levels: [SECONDARY], created_at: '2026-01-02T00:00:00Z', has_password: false, has_google: true, is_invited: false, last_login_at: null, papers_generated: 0 },
  // Predates the name fields — the table must still render the row.
  { id: 3, email: 'legacy@test.com', first_name: '', last_name: '', role: 'public', premium_school_levels: [], created_at: '2026-01-03T00:00:00Z', has_password: true, has_google: false, is_invited: false, last_login_at: null, papers_generated: 0 },
  // Pre-added by an admin, not yet claimed.
  { id: 4, email: 'invited@test.com', first_name: '', last_name: '', role: 'public', premium_school_levels: [PRIMARY], created_at: '2026-01-04T00:00:00Z', has_password: false, has_google: false, is_invited: true, last_login_at: null, papers_generated: 0 },
]

const setConfig = vi.fn()

describe('UsersList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    useSiteConfig.mockReturnValue({ protectImages: false, setConfig })
    api.users.list.mockResolvedValue(users)
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
    api.users.updateRole.mockResolvedValue({ id: 2, email: 'user@test.com', role: 'admin' })
    api.users.setPremiumSchoolLevels.mockResolvedValue({ id: 2, premium_school_levels: [] })
    api.users.remove.mockResolvedValue(null)
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
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
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

describe('UsersList account detail columns', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    useSiteConfig.mockReturnValue({ protectImages: false, setConfig })
    api.users.list.mockResolvedValue(users)
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
  })

  it('names how each account signs in', async () => {
    render(<UsersList />)
    await screen.findByText('user@test.com')
    expect(screen.getAllByText('Password').length).toBe(2)  // admin + legacy
    expect(screen.getByText('Google')).toBeInTheDocument()
  })

  it('flags an unclaimed invite so a mistyped address is visible', async () => {
    render(<UsersList />)
    expect(await screen.findByText('Invited')).toBeInTheDocument()
    // Listed like any other row, premium already granted.
    expect(screen.getByLabelText('Primary premium for invited@test.com')).toBeChecked()
  })

  it('shows Never for an account that has not signed in', async () => {
    render(<UsersList />)
    await screen.findByText('user@test.com')
    expect(screen.getAllByText('Never').length).toBe(3)
  })

  it('shows the papers-generated count', async () => {
    render(<UsersList />)
    await screen.findByText('admin@test.com')
    expect(screen.getByText('4')).toBeInTheDocument()
  })
})

describe('UsersList adding a user by email', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    useSiteConfig.mockReturnValue({ protectImages: false, setConfig })
    api.users.list.mockResolvedValue(users)
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
  })

  it('creates the account with its premium and adds the row', async () => {
    const user = userEvent.setup()
    api.users.create.mockResolvedValue({
      id: 9, email: 'new@test.com', first_name: 'New', last_name: 'Person', role: 'public',
      premium_school_levels: [SECONDARY], created_at: '2026-03-01T00:00:00Z',
      has_password: false, has_google: false, is_invited: true,
      last_login_at: null, papers_generated: 0,
    })
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByRole('button', { name: /add user by email/i }))
    await user.type(screen.getByLabelText('Email'), 'new@test.com')
    await user.type(screen.getByLabelText('First name'), 'New')
    await user.type(screen.getByLabelText('Last name'), 'Person')
    await user.click(screen.getByLabelText('Secondary premium for the new user'))
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    await waitFor(() => expect(api.users.create).toHaveBeenCalledWith({
      email: 'new@test.com',
      first_name: 'New',
      last_name: 'Person',
      role: 'public',
      school_level_ids: [SECONDARY.id],
    }))
    expect(await screen.findByText('new@test.com')).toBeInTheDocument()
  })

  it('keeps the dialog open and reports a duplicate address', async () => {
    const user = userEvent.setup()
    api.users.create.mockRejectedValue({ message: 'Email already registered' })
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByRole('button', { name: /add user by email/i }))
    await user.type(screen.getByLabelText('Email'), 'user@test.com')
    await user.click(screen.getByRole('button', { name: 'Add user' }))

    expect(await screen.findByText('Email already registered')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })
})

describe('UsersList deleting a user', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    useSiteConfig.mockReturnValue({ protectImages: false, setConfig })
    api.users.list.mockResolvedValue(users)
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
    api.users.remove.mockResolvedValue(null)
  })

  it('offers no delete on the admin\'s own row', async () => {
    render(<UsersList />)
    await screen.findByText('admin@test.com')
    expect(screen.queryByLabelText('Delete admin@test.com')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Delete user@test.com')).toBeInTheDocument()
  })

  it('confirms before deleting, then drops the row', async () => {
    const user = userEvent.setup()
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByLabelText('Delete user@test.com'))
    expect(api.users.remove).not.toHaveBeenCalled()  // confirmation first

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(api.users.remove).toHaveBeenCalledWith(2))
    await waitFor(() => expect(screen.queryByText('user@test.com')).not.toBeInTheDocument())
  })

  it('keeps the row and explains when the backend refuses', async () => {
    const user = userEvent.setup()
    api.users.remove.mockRejectedValue({ message: 'imported 3 paper(s) and cannot be deleted' })
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByLabelText('Delete user@test.com'))
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText(/cannot be deleted/)).toBeInTheDocument()
    // Still in the table (and named in the still-open dialog).
    expect(screen.getAllByText('user@test.com').length).toBeGreaterThan(0)
  })
})

describe('UsersList site settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { id: 1, email: 'admin@test.com', role: 'admin' } })
    useSiteConfig.mockReturnValue({ protectImages: false, setConfig })
    api.users.list.mockResolvedValue(users)
    api.schoolLevels.list.mockResolvedValue([SECONDARY, PRIMARY])
  })

  it('sends only protect_images so the About content is not clobbered', async () => {
    const user = userEvent.setup()
    api.siteConfig.update.mockResolvedValue({ about_content: '<p>x</p>', protect_images: true })
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByRole('checkbox', { name: /discourage copying/i }))

    await waitFor(() =>
      expect(api.siteConfig.update).toHaveBeenCalledWith({ protect_images: true })
    )
    expect(setConfig).toHaveBeenCalledWith({ about_content: '<p>x</p>', protect_images: true })
  })

  it('reports a failure to save the toggle', async () => {
    const user = userEvent.setup()
    api.siteConfig.update.mockRejectedValue({ message: 'Server unavailable' })
    render(<UsersList />)
    await screen.findByText('user@test.com')

    await user.click(screen.getByRole('checkbox', { name: /discourage copying/i }))
    expect(await screen.findByText('Server unavailable')).toBeInTheDocument()
  })
})
