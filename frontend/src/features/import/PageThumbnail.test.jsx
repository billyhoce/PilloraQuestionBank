import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PageThumbnail from './PageThumbnail'

const page = { url: 'blob:page-1', mergeWithPrev: false }

describe('PageThumbnail merge button', () => {
  it('is labelled "Merge with prev" when merging is allowed', () => {
    render(
      <PageThumbnail page={page} label="Q2" canMerge onToggleMerge={() => {}} onOpenLightbox={() => {}} />
    )
    expect(screen.getByRole('button', { name: /merge with prev/i })).toBeInTheDocument()
  })

  it('is hidden when merging is not allowed', () => {
    render(
      <PageThumbnail page={page} label="Q1" canMerge={false} onToggleMerge={() => {}} onOpenLightbox={() => {}} />
    )
    expect(screen.queryByRole('button', { name: /merge with prev/i })).not.toBeInTheDocument()
  })

  it('calls onToggleMerge when clicked', async () => {
    const user = userEvent.setup()
    const onToggleMerge = vi.fn()
    render(
      <PageThumbnail page={page} label="Q2" canMerge onToggleMerge={onToggleMerge} onOpenLightbox={() => {}} />
    )
    await user.click(screen.getByRole('button', { name: /merge with prev/i }))
    expect(onToggleMerge).toHaveBeenCalledTimes(1)
  })

  it('is highlighted when the page is merged', () => {
    render(
      <PageThumbnail
        page={{ ...page, mergeWithPrev: true }}
        label="Q1"
        canMerge
        onToggleMerge={() => {}}
        onOpenLightbox={() => {}}
      />
    )
    expect(screen.getByRole('button', { name: /merge with prev/i }).className).toContain('bg-blue-100')
  })
})

describe('PageThumbnail sizing', () => {
  it('scales with the grid cell via an A4 aspect ratio instead of a fixed height', () => {
    render(
      <PageThumbnail page={page} label="Q1" canMerge={false} onToggleMerge={() => {}} onOpenLightbox={() => {}} />
    )
    const img = screen.getByRole('img', { name: 'Q1' })
    expect(img.className).toContain('aspect-[210/297]')
    expect(img.style.height).toBe('')
  })
})
