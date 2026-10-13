import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ImportPage from './ImportPage'

vi.mock('./AutoImport', () => ({ default: () => <div>auto-import-view</div> }))
vi.mock('./ManualImport', () => ({ default: () => <div>manual-import-view</div> }))

beforeEach(() => sessionStorage.clear())

describe('ImportPage', () => {
  it('offers Auto-detect and Manual, defaulting to Auto-detect', async () => {
    render(<ImportPage />)
    expect(screen.getByRole('tab', { name: 'Auto-detect' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Manual' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByText('auto-import-view')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Manual' }))
    expect(screen.getByText('manual-import-view')).toBeInTheDocument()
    expect(screen.queryByText('auto-import-view')).toBeNull()
  })

  it('reopens on Manual when a manual import is in progress', () => {
    sessionStorage.setItem('pillora_import_session', '{"step":"review"}')
    render(<ImportPage />)
    expect(screen.getByText('manual-import-view')).toBeInTheDocument()
  })
})
