import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import SubscribePage from './SubscribePage'
import { useAuth } from '../context/AuthContext'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))

describe('SubscribePage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders pricing and a disabled Subscribe button for a normal user', () => {
    useAuth.mockReturnValue({ user: { id: 2, role: 'public' } })
    render(<SubscribePage />)
    expect(screen.getByText('Pillora Premium')).toBeInTheDocument()
    expect(screen.getByText(/\$9\.90/)).toBeInTheDocument()
    const button = screen.getByRole('button', { name: 'Subscribe' })
    expect(button).toBeDisabled()
  })

  it('tells premium users they already have access', () => {
    useAuth.mockReturnValue({ user: { id: 3, role: 'premium' } })
    render(<SubscribePage />)
    expect(screen.getByText(/already have premium access/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Subscribe' })).not.toBeInTheDocument()
  })
})
