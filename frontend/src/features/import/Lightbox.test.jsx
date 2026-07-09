import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Lightbox from './Lightbox'

const pages = [
  { url: 'blob:page-0', mergeWithPrev: false },
  { url: 'blob:page-1', mergeWithPrev: false },
  { url: 'blob:page-2', mergeWithPrev: true },
]

function renderLightbox(overrides = {}) {
  const props = {
    pages,
    currentIdx: 1,
    onClose: vi.fn(),
    onPrev: vi.fn(),
    onNext: vi.fn(),
    canMerge: (idx) => idx > 0,
    onToggleMerge: vi.fn(),
    ...overrides,
  }
  const utils = render(<Lightbox {...props} />)
  return { props, ...utils }
}

describe('Lightbox merge button', () => {
  it('shows "Merge with prev" for a mergeable page', () => {
    renderLightbox()
    expect(screen.getByRole('button', { name: /merge with prev/i })).toBeInTheDocument()
  })

  it('is hidden when the current page cannot merge (e.g. first page)', () => {
    renderLightbox({ currentIdx: 0 })
    expect(screen.queryByRole('button', { name: /merge with prev/i })).not.toBeInTheDocument()
  })

  it('is hidden when no merge props are provided (display-only usage)', () => {
    render(
      <Lightbox pages={pages} currentIdx={1} onClose={vi.fn()} onPrev={vi.fn()} onNext={vi.fn()} />
    )
    expect(screen.queryByRole('button', { name: /merge with prev/i })).not.toBeInTheDocument()
  })

  it('toggles merge for the current page without closing the lightbox', async () => {
    const user = userEvent.setup()
    const { props } = renderLightbox()
    await user.click(screen.getByRole('button', { name: /merge with prev/i }))
    expect(props.onToggleMerge).toHaveBeenCalledWith(1)
    expect(props.onClose).not.toHaveBeenCalled()
  })

  it('is highlighted when the current page is merged', () => {
    renderLightbox({ currentIdx: 2 })
    expect(screen.getByRole('button', { name: /merge with prev/i }).className).toContain('bg-blue-100')
  })

  it('reflects the newly shown page after navigation', () => {
    const { rerender, props } = renderLightbox({ currentIdx: 1 })
    let btn = screen.getByRole('button', { name: /merge with prev/i })
    expect(btn.className).not.toContain('bg-blue-100')

    rerender(<Lightbox {...props} currentIdx={2} />)
    btn = screen.getByRole('button', { name: /merge with prev/i })
    expect(btn.className).toContain('bg-blue-100')
  })
})
