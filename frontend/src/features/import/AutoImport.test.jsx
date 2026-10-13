import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AutoImport, { POLL_MS } from './AutoImport'
import { waitingDays } from './jobAge'
import { api } from '../../api/client'

vi.mock('../../api/client', async importActual => ({
  api: {
    import: {
      // the real upload flow (fetch + XHR are stubbed per test)
      uploadJob: (await importActual()).api.import.uploadJob,
      listJobs: vi.fn(),
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
  api.import.cancelJob.mockResolvedValue(null)
})

const daysAgo = n => new Date(Date.now() - n * 24 * 60 * 60 * 1000 - 60 * 1000).toISOString()

describe('AutoImport', () => {
  it('shows a failed job\'s reason in the list', async () => {
    api.import.listJobs.mockResolvedValue(listing([
      { id: 'f', filename: 'locked.pdf', status: 'failed', error: 'register failed: The PDF is password protected', created_at: daysAgo(1) },
    ]))
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    expect(await screen.findByText(/The PDF is password protected/)).toBeInTheDocument()
  })

  it('shows an age badge on unsettled jobs, highlighted past 14 days', async () => {
    api.import.listJobs.mockResolvedValue(listing([
      { id: 'a', filename: 'young.pdf', status: 'review_ready', created_at: daysAgo(12) },
      { id: 'b', filename: 'edge.pdf', status: 'failed', created_at: daysAgo(14) },
      { id: 'c', filename: 'old.pdf', status: 'review_ready', created_at: daysAgo(15) },
      { id: 'd', filename: 'done.pdf', status: 'confirmed', created_at: daysAgo(40) },
      { id: 'e', filename: 'gone.pdf', status: 'cancelled', created_at: daysAgo(40) },
    ]))
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await screen.findByText('young.pdf')
    const badges = screen.getAllByTestId('age-badge')
    expect(badges.map(b => b.textContent)).toEqual(['waiting 12 days', 'waiting 14 days', 'waiting 15 days'])
    expect(badges.map(b => b.dataset.stale)).toEqual(['false', 'false', 'true'])
  })

  it('computes waiting days from created_at', () => {
    expect(waitingDays('2026-10-01T00:00:00Z', Date.parse('2026-10-13T12:00:00Z'))).toBe(12)
    expect(waitingDays('garbage')).toBeNull()
  })

  it('the Awaiting review filter asks the server for review_ready and failed jobs only', async () => {
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await screen.findByText('second.pdf')
    await userEvent.click(screen.getByLabelText('Awaiting review'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith('review_ready,failed', {}))
    await userEvent.click(screen.getByLabelText('Awaiting review'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, {}))
  })

  it('the Unmatched answers filter combines with the other filters', async () => {
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await screen.findByText('second.pdf')
    await userEvent.click(screen.getByLabelText('Unmatched answers'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { unmatched_answers: true }))
    await userEvent.type(screen.getByLabelText('Search jobs by job id or paper id'), '42{enter}')
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { paper_id: '42', unmatched_answers: true }))
    await userEvent.click(screen.getByLabelText('Awaiting review'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith('review_ready,failed', { paper_id: '42', unmatched_answers: true }))
    await userEvent.click(screen.getByLabelText('Unmatched answers'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith('review_ready,failed', { paper_id: '42' }))
  })

  it('lists jobs with filename and status; only live jobs can be cancelled', async () => {
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    expect(await screen.findByText('second.pdf')).toBeInTheDocument()
    expect(screen.getByText('first.pdf')).toBeInTheDocument()
    expect(screen.getByText('Queued')).toBeInTheDocument()
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
  })

  it('searches by job id or paper id', async () => {
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await screen.findByText('second.pdf')
    const box = screen.getByLabelText('Search jobs by job id or paper id')
    await userEvent.type(box, '42{enter}')
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { paper_id: '42' }))
    const id = '0b1c2d3e-0000-4000-8000-000000000001'
    await userEvent.clear(box)
    await userEvent.type(box, `${id}{enter}`)
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { job_id: id }))
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, {}))
  })

  it('shows an empty state', async () => {
    api.import.listJobs.mockResolvedValue(listing([]))
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    expect(await screen.findByText('No import jobs yet.')).toBeInTheDocument()
  })

  describe('direct-to-S3 upload', () => {
    let xhrs
    let fetchMock

    class FakeXhr {
      constructor() { this.upload = {}; xhrs.push(this) }
      open(method, url) { this.method = method; this.url = url }
      send(form) { this.form = form }
    }

    const jsonRes = (status, body) => ({ ok: status < 400, status, json: async () => body })

    beforeEach(() => {
      xhrs = []
      vi.stubGlobal('XMLHttpRequest', FakeXhr)
      fetchMock = vi.fn(async (url, opts) => {
        if (url === '/api/import/uploads') {
          return jsonRes(201, { job_id: 'j3', url: 'https://s3.test/bucket', fields: { key: 'ingest/j3/source.pdf', 'Content-Type': 'application/pdf' } })
        }
        if (opts.method === 'DELETE') return { ok: true, status: 204 }
        return jsonRes(200, { job_id: 'j3', status: 'queued' })
      })
      vi.stubGlobal('fetch', fetchMock)
    })
    afterEach(() => vi.unstubAllGlobals())

    const dropFile = async container => {
      const file = new File(['%PDF'], 'new.pdf', { type: 'application/pdf' })
      await userEvent.upload(container.querySelector('input[type=file]'), file)
      return file
    }
    const calls = () => fetchMock.mock.calls.map(([url, opts]) => `${opts.method} ${url}`)

    it('shows per-file progress, then marks the job uploaded and refreshes the list', async () => {
      const { container } = render(<MemoryRouter><AutoImport /></MemoryRouter>)
      await screen.findByText('second.pdf')
      const file = await dropFile(container)

      await waitFor(() => expect(xhrs).toHaveLength(1))
      const [xhr] = xhrs
      expect(xhr.method).toBe('POST')
      expect(xhr.url).toBe('https://s3.test/bucket')
      expect([...xhr.form.keys()]).toEqual(['key', 'Content-Type', 'file'])
      expect(xhr.form.get('file')).toBe(file)
      expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ filename: 'new.pdf', size: file.size })

      act(() => xhr.upload.onprogress({ lengthComputable: true, loaded: 25, total: 100 }))
      expect(await screen.findByLabelText('Upload progress of new.pdf')).toHaveAttribute('value', '25')
      expect(calls()).toEqual(['POST /api/import/uploads'])

      api.import.listJobs.mockResolvedValue(listing([
        { id: 'j3', filename: 'new.pdf', status: 'queued', created_at: '2026-10-08T10:00:00Z' }, ...JOBS,
      ]))
      xhr.status = 204
      act(() => xhr.onload())
      await waitFor(() => expect(calls()).toEqual(['POST /api/import/uploads', 'POST /api/import/jobs/j3/uploaded']))
      expect(await screen.findByText('new.pdf')).toBeInTheDocument()
      expect(screen.queryByLabelText('Upload progress of new.pdf')).not.toBeInTheDocument()
    })

    it('cancels the job and shows the error when the S3 POST fails', async () => {
      const { container } = render(<MemoryRouter><AutoImport /></MemoryRouter>)
      await screen.findByText('second.pdf')
      await dropFile(container)
      await waitFor(() => expect(xhrs).toHaveLength(1))
      xhrs[0].status = 403
      act(() => xhrs[0].onload())
      expect(await screen.findByText(/Upload to storage failed/)).toBeInTheDocument()
      expect(calls()).toEqual(['POST /api/import/uploads', 'DELETE /api/import/jobs/j3'])
    })
  })

  it('cancels a job after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(api.import.cancelJob).toHaveBeenCalledWith('j2'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenCalledTimes(2))
  })

  it('does not cancel when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(api.import.cancelJob).not.toHaveBeenCalled()
  })

  it('shows the upload error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403, json: async () => ({ detail: 'Only PDF files are accepted' }) })))
    const { container } = render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await screen.findByText('second.pdf')
    await userEvent.upload(
      container.querySelector('input[type=file]'),
      new File(['x'], 'a.pdf', { type: 'application/pdf' }),
    )
    expect(await screen.findByText('Only PDF files are accepted')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('shows stage, progress, warnings and the needs-review marker', async () => {
    api.import.listJobs.mockResolvedValue(listing([{
      ...JOBS[1], status: 'review_ready', stage: 'report', tasks_done: 7, tasks_total: 9,
      warnings_count: 2, needs_review: true,
    }]))
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    expect(await screen.findByText('7/9 tasks')).toBeInTheDocument()
    expect(screen.getByText('report')).toBeInTheDocument()
    expect(screen.getByText('2 warnings')).toBeInTheDocument()
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '9')
  })

  it('retries a job and refreshes', async () => {
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
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
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'second.pdf' }))
    expect(await screen.findByText('1.5 s')).toBeInTheDocument()
    expect(screen.getByText('odd page')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(api.import.getJob).toHaveBeenCalledWith('j2')
  })

  it('shows the traceback of a failed task, and none for other tasks', async () => {
    api.import.getJob.mockResolvedValue({
      ...JOBS[0],
      tasks: [
        { id: 1, stage: 'register', section: null, status: 'done', duration_ms: 10, warnings: [], reason: '', error: '', traceback: '' },
        { id: 2, stage: 'segment', section: null, status: 'failed', duration_ms: null, warnings: [], reason: '', error: 'KeyError: x', traceback: 'Traceback (most recent call last):\n  File "s.py", line 3\nKeyError: x' },
      ],
    })
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: 'second.pdf' }))
    await userEvent.click(await screen.findByText('Traceback'))
    expect(screen.getByText(/File "s.py", line 3/)).toBeInTheDocument()
    expect(screen.getAllByText('Traceback')).toHaveLength(1)
  })

  describe('polling and worker state', () => {
    afterEach(() => vi.useRealTimers())

    async function tick() {
      await act(async () => { await vi.advanceTimersByTimeAsync(POLL_MS) })
    }

    it('polls every 3 s while a job is queued or running, and stops when none is', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      render(<MemoryRouter><AutoImport /></MemoryRouter>)
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
      const idle = render(<MemoryRouter><AutoImport /></MemoryRouter>)
      await screen.findByText('first.pdf')
      await tick()
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(1)
      idle.unmount()

      api.import.listJobs.mockResolvedValue(listing(JOBS))
      const { unmount } = render(<MemoryRouter><AutoImport /></MemoryRouter>)
      await screen.findByText('second.pdf')
      const before = api.import.listJobs.mock.calls.length
      unmount()
      await tick()
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(before)
    })

    it('warns "worker offline" when jobs are waiting and the heartbeat is stale', async () => {
      api.import.listJobs.mockResolvedValue(listing(JOBS, false))
      render(<MemoryRouter><AutoImport /></MemoryRouter>)
      expect(await screen.findByRole('alert')).toHaveTextContent('Worker offline')
      expect(screen.getByText('Worker offline', { selector: 'div' })).toBeInTheDocument()
    })

    it('shows no offline warning while the worker is alive', async () => {
      render(<MemoryRouter><AutoImport /></MemoryRouter>)
      await screen.findByText('second.pdf')
      expect(screen.queryByText(/worker offline/i)).not.toBeInTheDocument()
    })

    it('shows no offline warning when nothing is waiting', async () => {
      api.import.listJobs.mockResolvedValue(listing([JOBS[1]], false))
      render(<MemoryRouter><AutoImport /></MemoryRouter>)
      await screen.findByText('first.pdf')
      expect(screen.queryByText(/worker offline/i)).not.toBeInTheDocument()
    })
  })

  it('links review-ready jobs to their review page', async () => {
    api.import.listJobs.mockResolvedValue(
      listing([{ id: 'j9', filename: 'r.pdf', status: 'review_ready', created_at: '2026-10-07T10:00:00Z' }]),
    )
    render(<MemoryRouter><AutoImport /></MemoryRouter>)
    expect(await screen.findByRole('link', { name: 'Review' })).toHaveAttribute('href', '/admin/import/jobs/j9/review')
  })
})
