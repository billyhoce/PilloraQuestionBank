import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AutoImport from './AutoImport'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    import: {
      listJobs: vi.fn(),
      createJob: vi.fn(),
      cancelJob: vi.fn(),
    },
  },
}))

const JOBS = [
  { id: 'j2', filename: 'second.pdf', status: 'queued', created_at: '2026-10-07T10:00:00Z' },
  { id: 'j1', filename: 'first.pdf', status: 'confirmed', created_at: '2026-10-06T10:00:00Z' },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.import.listJobs.mockResolvedValue(JOBS)
  api.import.createJob.mockResolvedValue({ job_id: 'j3' })
  api.import.cancelJob.mockResolvedValue(null)
})

describe('AutoImport', () => {
  it('lists jobs with filename and status; only live jobs can be cancelled', async () => {
    render(<AutoImport />)
    expect(await screen.findByText('second.pdf')).toBeInTheDocument()
    expect(screen.getByText('first.pdf')).toBeInTheDocument()
    expect(screen.getByText('Queued')).toBeInTheDocument()
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
  })

  it('shows an empty state', async () => {
    api.import.listJobs.mockResolvedValue([])
    render(<AutoImport />)
    expect(await screen.findByText('No import jobs yet.')).toBeInTheDocument()
  })

  it('uploads a dropped PDF as a job and refreshes the list', async () => {
    const { container } = render(<AutoImport />)
    await screen.findByText('second.pdf')
    const file = new File(['%PDF'], 'new.pdf', { type: 'application/pdf' })
    await userEvent.upload(container.querySelector('input[type=file]'), file)
    await waitFor(() => expect(api.import.createJob).toHaveBeenCalledWith(file))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenCalledTimes(2))
  })

  it('cancels a job after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<AutoImport />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(api.import.cancelJob).toHaveBeenCalledWith('j2'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenCalledTimes(2))
  })

  it('does not cancel when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<AutoImport />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(api.import.cancelJob).not.toHaveBeenCalled()
  })

  it('shows the upload error', async () => {
    api.import.createJob.mockRejectedValue({ message: 'Only PDF files are accepted' })
    const { container } = render(<AutoImport />)
    await screen.findByText('second.pdf')
    await userEvent.upload(
      container.querySelector('input[type=file]'),
      new File(['x'], 'a.pdf', { type: 'application/pdf' }),
    )
    expect(await screen.findByText('Only PDF files are accepted')).toBeInTheDocument()
  })
})
