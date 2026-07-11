import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PageGrid from './PageGrid'

const pages = Array.from({ length: 6 }, (_, i) => ({
  temp_key: `tmp/page_${i}.webp`,
  url: `blob:page-${i}`,
  mergeWithPrev: false,
}))

function renderGrid() {
  return render(
    <PageGrid
      pages={pages}
      dividerIdx={null}
      onToggleMerge={() => {}}
      onSetDivider={() => {}}
      onRemoveDivider={() => {}}
    />
  )
}

describe('PageGrid layout', () => {
  it('caps the grid at 5 pages per row', () => {
    const { container } = renderGrid()
    const grid = container.querySelector('.grid')
    expect(grid.className).toContain('lg:grid-cols-5')
    expect(grid.className).not.toContain('grid-cols-8')
  })

  it('renders every page with its question label', () => {
    renderGrid()
    for (let i = 1; i <= 6; i++) {
      expect(screen.getByText(`Q${i}`)).toBeInTheDocument()
    }
  })
})
