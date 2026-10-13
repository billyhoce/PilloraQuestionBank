import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ProtectedImage from './ProtectedImage'
import { useAuth } from '../context/AuthContext'
import { useSiteConfig } from '../context/SiteConfigContext'

vi.mock('../context/AuthContext', () => ({ useAuth: vi.fn() }))
vi.mock('../context/SiteConfigContext', () => ({ useSiteConfig: vi.fn() }))

function setup({ protectImages, role = 'public' }) {
  useAuth.mockReturnValue({ user: role ? { role } : null })
  useSiteConfig.mockReturnValue({ protectImages })
}

beforeEach(() => vi.clearAllMocks())

describe('ProtectedImage with protection off', () => {
  it('renders a bare img that still allows the context menu', () => {
    setup({ protectImages: false })
    render(<ProtectedImage src="/q.webp" alt="Q1" className="w-full" />)

    const img = screen.getByAltText('Q1')
    expect(img.tagName).toBe('IMG')
    expect(img.className).toBe('w-full')
    expect(fireEvent.contextMenu(img)).toBe(true) // not prevented
  })
})

describe('ProtectedImage with protection on', () => {
  it('blocks the context menu and dragging', () => {
    setup({ protectImages: true })
    render(<ProtectedImage src="/q.webp" alt="Q1" />)

    const img = screen.getByAltText('Q1')
    // fireEvent returns false when the event was defaultPrevented.
    expect(fireEvent.contextMenu(img)).toBe(false)
    expect(fireEvent.dragStart(img)).toBe(false)
    expect(img).toHaveAttribute('draggable', 'false')
  })

  it('applies the class that suppresses selection and the iOS long-press sheet', () => {
    setup({ protectImages: true })
    render(<ProtectedImage src="/q.webp" alt="Q1" className="w-full" />)

    const img = screen.getByAltText('Q1')
    expect(img.className).toContain('protected-image')
    expect(img.className).toContain('w-full') // caller's classes survive
  })

  it('covers the image with a transparent overlay', () => {
    setup({ protectImages: true })
    const { container } = render(<ProtectedImage src="/q.webp" alt="Q1" />)

    const overlay = container.querySelector('[aria-hidden="true"]')
    expect(overlay).toBeInTheDocument()
    expect(overlay.className).toContain('absolute')
    expect(overlay.className).toContain('inset-0')
  })

  it('still lets a click reach the card wrapping it', () => {
    // QuestionCard nests the preview inside a <button>; the overlay must not
    // swallow that click or opening a question would break whenever the toggle
    // is on.
    setup({ protectImages: true })
    const onClick = vi.fn()
    const { container } = render(
      <button type="button" onClick={onClick}>
        <ProtectedImage src="/q.webp" alt="Q1" />
      </button>
    )

    fireEvent.click(container.querySelector('[aria-hidden="true"]'))
    expect(onClick).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByAltText('Q1'))
    expect(onClick).toHaveBeenCalledTimes(2)
  })

  it('exempts admins, who need to save images while importing', () => {
    setup({ protectImages: true, role: 'admin' })
    render(<ProtectedImage src="/q.webp" alt="Q1" />)

    const img = screen.getByAltText('Q1')
    expect(fireEvent.contextMenu(img)).toBe(true)
    expect(img).not.toHaveAttribute('draggable')
  })
})

describe('ProtectedImage without providers', () => {
  it('falls back to an unprotected image rather than crashing', () => {
    // Cards are rendered in tests (and could be rendered outside the shell)
    // without either context mounted.
    useAuth.mockReturnValue(null)
    useSiteConfig.mockReturnValue({ protectImages: false })
    render(<ProtectedImage src="/q.webp" alt="Q1" />)
    expect(screen.getByAltText('Q1').tagName).toBe('IMG')
  })
})
