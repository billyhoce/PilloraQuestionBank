import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import UserMenu from './UserMenu'
import { useAuth } from '../context/AuthContext'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

const logout = vi.fn().mockResolvedValue(undefined)

function renderMenu() {
  render(
    <MemoryRouter>
      <UserMenu />
      <span>outside</span>
    </MemoryRouter>
  )
}

describe('UserMenu dropdown', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({ user: { email: 'user@example.com', role: 'public' }, logout })
  })

  it('hides Log out until the account button is clicked', async () => {
    const user = userEvent.setup()
    renderMenu()
    expect(screen.queryByRole('menuitem', { name: 'Log out' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /user@example\.com/ }))
    expect(screen.getByRole('menuitem', { name: 'Log out' })).toBeInTheDocument()
  })

  it('calls logout when Log out is clicked', async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole('button', { name: /user@example\.com/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Log out' }))
    expect(logout).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole('button', { name: /user@example\.com/ }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('menuitem', { name: 'Log out' })).not.toBeInTheDocument()
  })

  it('closes on outside click', async () => {
    const user = userEvent.setup()
    renderMenu()
    await user.click(screen.getByRole('button', { name: /user@example\.com/ }))
    await user.click(screen.getByText('outside'))
    expect(screen.queryByRole('menuitem', { name: 'Log out' })).not.toBeInTheDocument()
  })
})
