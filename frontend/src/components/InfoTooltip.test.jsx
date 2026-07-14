import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import InfoTooltip from './InfoTooltip'

describe('InfoTooltip', () => {
  it('renders the trigger button with the given aria-label', () => {
    render(<InfoTooltip label="What does this do?">Helpful text.</InfoTooltip>)
    expect(screen.getByRole('button', { name: 'What does this do?' })).toBeInTheDocument()
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('reveals the content on hover', async () => {
    const user = userEvent.setup()
    render(<InfoTooltip label="Info">Helpful text.</InfoTooltip>)
    await user.hover(screen.getByRole('button', { name: 'Info' }))
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Helpful text.')
  })

  it('pins the tooltip open on click', async () => {
    const user = userEvent.setup()
    render(<InfoTooltip label="Info">Pinned text.</InfoTooltip>)
    const btn = screen.getByRole('button', { name: 'Info' })
    await user.click(btn)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Pinned text.')
    // Moving the pointer away keeps it open while pinned.
    await user.unhover(btn)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })
})
