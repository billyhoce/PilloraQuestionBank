import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Route, Routes, useOutletContext } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import ImportLayout from './ImportLayout'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({ api: { import: { listJobs: vi.fn() } } }))

function Child() {
  const { reviewQueue } = useOutletContext()
  return <div data-testid="child">{reviewQueue.jobs ? `${reviewQueue.jobs.length} in queue` : 'loading'}</div>
}

const renderAt = path => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route element={<ImportLayout />}>
        <Route path="/admin/import/auto" element={<Child />} />
        <Route path="/admin/import/jobs/:jobId/review" element={<Child />} />
      </Route>
    </Routes>
  </MemoryRouter>,
)

beforeEach(() => {
  vi.clearAllMocks()
  api.import.listJobs.mockResolvedValue({ jobs: [{ id: 'a' }, { id: 'b' }], workerAlive: true })
})

describe('ImportLayout', () => {
  it('links the three import pages and counts the review queue, shared with the page', async () => {
    renderAt('/admin/import/auto')
    expect(screen.getByRole('link', { name: 'Auto import' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Manual import' })).toHaveAttribute('href', '/admin/import/manual')
    expect(await screen.findByLabelText('2 ready for review')).toBeInTheDocument()
    expect(screen.getByTestId('child')).toHaveTextContent('2 in queue')
    expect(api.import.listJobs).toHaveBeenCalledTimes(1)
    expect(api.import.listJobs).toHaveBeenCalledWith('review_ready')
  })

  it('treats a job review page as part of the review queue', async () => {
    renderAt('/admin/import/jobs/x/review')
    expect(screen.getByRole('link', { name: /Review queue/ })).toHaveAttribute('aria-current', 'page')
    await screen.findByLabelText('2 ready for review')
  })
})
