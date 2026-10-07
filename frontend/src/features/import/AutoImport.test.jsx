import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AutoImport, { POLL_MS } from './AutoImport'
import { api } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    import: {
      listJobs: vi.fn(),
      createJob: vi.fn(),
      cancelJob: vi.fn(),
      retryJob: vi.fn(),
      getJob: vi.fn(),
    },
  },
}))

const JOBS = [
  { id: 'j2', filename: 'second.pdf', status: 'queued', created_at: '2026-10-07T10:00:00Z' },
  { id: 'j1', filename: 'first.pdf', status: 'confirmed', created_at: '2026-10-06T10:00:00Z' },
]

const listing = (jobs, workerAlive = true) => ({ jobs, workerAlive, heartbeatAgeS: workerAlive ? 5 : 400 })

beforeEach(() => {
  vi.clearAllMocks()
  api.import.listJobs.mockResolvedValue(listing(JOBS))
  api.import.retryJob.mockResolvedValue({})
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
    api.import.listJobs.mockResolvedValue(listing([]))
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

  it('shows stage, progress, warnings and the needs-review marker', async () => {
    api.import.listJobs.mockResolvedValue(listing([{
      ...JOBS[1], status: 'review_ready', stage: 'report', tasks_done: 7, tasks_total: 9,
      warnings_count: 2, needs_review: true,
    }]))
    render(<AutoImport />)
    expect(await screen.findByText('7/9 tasks')).toBeInTheDocument()
    expect(screen.getByText('report')).toBeInTheDocument()
    expect(screen.getByText('2 warnings')).toBeInTheDocument()
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '9')
  })

  it('retries a job and refreshes', async () => {
    render(<AutoImport />)
    await userEvent.click((await screen.findAllByRole('button', { name: 'Retry' }))[0])
    await waitFor(() => expect(api.import.retryJob).toHaveBeenCalledWith('j2'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenCalledTimes(2))
  })

  it('lists every task in the job detail', async () => {
    api.import.getJob.mockResolvedValue({
      ...JOBS[0],
      tasks: [
        { id: 1, stage: 'register', section: null, status: 'done', duration_ms: 1500, warnings: ['odd page'], reason: '', error: '' },
        { id: 2, stage: 'segment', section: null, status: 'failed', duration_ms: null, warnings: [], reason: '', error: 'boom' },
      ],
    })
    render(<AutoImport />)
    await userEvent.click(await screen.findByRole('button', { name: 'second.pdf' }))
    expect(await screen.findByText('1.5 s')).toBeInTheDocument()
    expect(screen.getByText('odd page')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(api.import.getJob).toHaveBeenCalledWith('j2')
  })

  describe('polling and worker state', () => {
    afterEach(() => vi.useRealTimers())

    async function tick() {
      await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS) })
    }

    it('polls every 3 s while a job is queued or running, and stops when none is', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      render(<AutoImport />)
      await screen.findByText('second.pdf')
      expect(api.import.listJobs).toHaveBeenCalledTimes(1)

      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(2)
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(3)

      // The job finishes: the next poll returns nothing active, then polling stops.
      api.import.listJobs.mockResolvedValue(listing([{ ...JOBS[0], status: 'review_ready' }]))
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(4)
      await tick()
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(4)
    })

    it('does not poll when no job is active, and stops on unmount', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      api.import.listJobs.mockResolvedValue(listing([{ ...JOBS[1] }]))
      const idle = render(<AutoImport />)
      await screen.findByText('first.pdf')
      await tick()
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(1)
      idle.unmount()

      api.import.listJobs.mockResolvedValue(listing(JOBS))
      const { unmount } = render(<AutoImport />)
      await screen.findByText('second.pdf')
      const before = api.import.listJobs.mock.calls.length
      unmount()
      await tick()
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(before)
    })

    it('warns "worker offline" when jobs are waiting and the heartbeat is stale', async () => {
      api.import.listJobs.mockResolvedValue(listing(JOBS, false))
      render(<AutoImport />)
      expect(await screen.findByRole('alert')).toHaveTextContent('Worker offline')
      expect(screen.getByText('Worker offline', { selector: 'div' })).toBeInTheDocument()
    })

    it('shows no offline warning while the worker is alive', async () => {
      render(<AutoImport />)
      await screen.findByText('second.pdf')
      expect(screen.queryByText(/worker offline/i)).not.toBeInTheDocument()
    })

    it('shows no offline warning when nothing is waiting', async () => {
      api.import.listJobs.mockResolvedValue(listing([JOBS[1]], false))
      render(<AutoImport />)
      await screen.findByText('first.pdf')
      expect(screen.queryByText(/worker offline/i)).not.toBeInTheDocument()
    })
  })
})
