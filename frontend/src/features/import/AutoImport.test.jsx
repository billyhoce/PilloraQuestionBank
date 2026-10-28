import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, waitFor, act, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AutoImport, { IDLE_POLL_MS, POLL_MS } from './AutoImport'
import { UploadQueueProvider } from './UploadQueue'
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

const renderPage = () => render(
  <MemoryRouter><UploadQueueProvider><AutoImport /></UploadQueueProvider></MemoryRouter>,
)
const board = () => screen.getByRole('list', { name: 'Jobs in progress' })
const history = () => screen.getByRole('region', { name: 'All jobs' })

beforeEach(() => {
  vi.clearAllMocks()
  api.import.listJobs.mockResolvedValue(listing(JOBS))
  api.import.retryJob.mockResolvedValue({})
  api.import.cancelJob.mockResolvedValue(null)
})

const daysAgo = n => new Date(Date.now() - n * 24 * 60 * 60 * 1000 - 60 * 1000).toISOString()

describe('AutoImport', () => {
  it('puts jobs still in the pipeline on the board and every job in the history', async () => {
    renderPage()
    await screen.findAllByText('second.pdf')
    expect(within(board()).getByText('second.pdf')).toBeInTheDocument()
    expect(within(board()).queryByText('first.pdf')).toBeNull()
    expect(within(history()).getByText('first.pdf')).toBeInTheDocument()
    expect(within(history()).getByText('Confirmed')).toBeInTheDocument()
    expect(within(history()).getAllByRole('button', { name: 'Cancel' })).toHaveLength(1)
  })

  it('shows a failed job\'s reason and step on the board, with Retry', async () => {
    api.import.listJobs.mockResolvedValue(listing([
      { id: 'f', filename: 'locked.pdf', status: 'failed', tasks_failed: 1, error: 'register failed: The PDF is password protected', created_at: daysAgo(1) },
    ]))
    renderPage()
    await screen.findAllByText('locked.pdf')
    expect(within(board()).getByText(/The PDF is password protected/)).toBeInTheDocument()
    expect(within(board()).getByText('Failed at Read PDF')).toBeInTheDocument()
    expect(within(board()).getByText('Read PDF: failed')).toBeInTheDocument()
    await userEvent.click(within(board()).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(api.import.retryJob).toHaveBeenCalledWith('f'))
  })

  it('shows the step in hand, the task count, warnings and a progress bar for a running job', async () => {
    api.import.listJobs.mockResolvedValue(listing([{
      id: 'r', filename: 'run.pdf', status: 'running', stage: 'locate', tasks_done: 7, tasks_total: 9,
      warnings_count: 2, page_count: 24, created_at: daysAgo(0),
    }]))
    renderPage()
    await screen.findAllByText('run.pdf')
    const b = within(board())
    expect(b.getByText(/Extract questions · 7\/9 tasks/)).toBeInTheDocument()
    expect(b.getByText(/24 pages/)).toBeInTheDocument()
    expect(b.getByText(/2 warnings/)).toBeInTheDocument()
    expect(b.getByLabelText('Progress of run.pdf')).toHaveAttribute('max', '9')
    expect(b.getByText('Split: done')).toBeInTheDocument()
    expect(b.getByText('Extract questions: active')).toBeInTheDocument()
    expect(b.getByText('Assemble: todo')).toBeInTheDocument()
  })

  it('counts the jobs and links to the review queue', async () => {
    api.import.listJobs.mockResolvedValue(listing([
      ...JOBS,
      { id: 'a', filename: 'a.pdf', status: 'review_ready', created_at: daysAgo(0) },
      { id: 'b', filename: 'b.pdf', status: 'review_ready', created_at: daysAgo(0) },
    ]))
    renderPage()
    expect(await screen.findByRole('link', { name: '2 jobs ready for review →' })).toHaveAttribute('href', '/admin/import/review')
  })

  it('shows an age badge on unsettled jobs, highlighted past 14 days', async () => {
    api.import.listJobs.mockResolvedValue(listing([
      { id: 'a', filename: 'young.pdf', status: 'review_ready', created_at: daysAgo(12) },
      { id: 'b', filename: 'edge.pdf', status: 'failed', created_at: daysAgo(14) },
      { id: 'c', filename: 'old.pdf', status: 'review_ready', created_at: daysAgo(15) },
      { id: 'd', filename: 'done.pdf', status: 'confirmed', created_at: daysAgo(40) },
      { id: 'e', filename: 'gone.pdf', status: 'cancelled', created_at: daysAgo(40) },
    ]))
    renderPage()
    await screen.findByText('young.pdf')
    const badges = within(history()).getAllByTestId('age-badge')
    expect(badges.map(b => b.textContent)).toEqual(['waiting 12 days', 'waiting 14 days', 'waiting 15 days'])
    expect(badges.map(b => b.dataset.stale)).toEqual(['false', 'false', 'true'])
  })

  it('computes waiting days from created_at', () => {
    expect(waitingDays('2026-10-01T00:00:00Z', Date.parse('2026-10-13T12:00:00Z'))).toBe(12)
    expect(waitingDays('garbage')).toBeNull()
  })

  it('the history\'s Awaiting review filter asks the server for review_ready and failed jobs only', async () => {
    renderPage()
    await screen.findAllByText('second.pdf')
    expect(api.import.listJobs).toHaveBeenLastCalledWith()
    await userEvent.click(screen.getByLabelText('Awaiting review'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith('review_ready,failed', {}))
  })

  it('the Unmatched answers filter combines with the other filters', async () => {
    renderPage()
    await screen.findAllByText('second.pdf')
    await userEvent.click(screen.getByLabelText('Unmatched answers'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { unmatched_answers: true }))
    await userEvent.type(screen.getByLabelText('Search jobs by job id or paper id'), '42{enter}')
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { paper_id: '42', unmatched_answers: true }))
    await userEvent.click(screen.getByLabelText('Awaiting review'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith('review_ready,failed', { paper_id: '42', unmatched_answers: true }))
    await userEvent.click(screen.getByLabelText('Unmatched answers'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith('review_ready,failed', { paper_id: '42' }))
  })

  it('searches by job id or paper id', async () => {
    renderPage()
    await screen.findAllByText('second.pdf')
    const box = screen.getByLabelText('Search jobs by job id or paper id')
    await userEvent.type(box, '42{enter}')
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { paper_id: '42' }))
    const id = '0b1c2d3e-0000-4000-8000-000000000001'
    await userEvent.clear(box)
    await userEvent.type(box, `${id}{enter}`)
    await waitFor(() => expect(api.import.listJobs).toHaveBeenLastCalledWith(undefined, { job_id: id }))
    api.import.listJobs.mockResolvedValue(listing([]))
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
    // Unfiltered again: the history shows the board's own list (no extra request).
    expect(within(history()).getByText('first.pdf')).toBeInTheDocument()
  })

  it('shows empty states', async () => {
    api.import.listJobs.mockResolvedValue(listing([]))
    renderPage()
    expect(await screen.findByText('No import jobs yet.')).toBeInTheDocument()
    expect(screen.getByText(/Nothing is processing/)).toBeInTheDocument()
  })

  it('cancels a job after confirmation, and not when declined', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()
    await screen.findAllByText('second.pdf')
    await userEvent.click(within(board()).getByRole('button', { name: 'Cancel' }))
    expect(api.import.cancelJob).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    await userEvent.click(within(board()).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(api.import.cancelJob).toHaveBeenCalledWith('j2'))
    await waitFor(() => expect(api.import.listJobs).toHaveBeenCalledTimes(2))
  })

  it('lists every task in the job detail, with a failed task\'s traceback', async () => {
    api.import.getJob.mockResolvedValue({
      ...JOBS[0],
      tasks: [
        { id: 1, stage: 'register', section: null, status: 'done', duration_ms: 1500, warnings: ['odd page'], reason: '', error: '', traceback: '' },
        { id: 2, stage: 'segment', section: null, status: 'failed', duration_ms: null, warnings: [], reason: '', error: 'KeyError: x', traceback: 'Traceback (most recent call last):\n  File "s.py", line 3\nKeyError: x' },
      ],
    })
    renderPage()
    await screen.findAllByText('second.pdf')
    await userEvent.click(within(board()).getByRole('button', { name: 'second.pdf' }))
    expect(await screen.findByText('1.5 s')).toBeInTheDocument()
    expect(screen.getByText('odd page')).toBeInTheDocument()
    expect(api.import.getJob).toHaveBeenCalledWith('j2')
    await userEvent.click(screen.getByText('Traceback'))
    expect(screen.getByText(/File "s.py", line 3/)).toBeInTheDocument()
    expect(screen.getAllByText('Traceback')).toHaveLength(1)
  })

  it('links review-ready jobs in the history to their review page', async () => {
    api.import.listJobs.mockResolvedValue(
      listing([{ id: 'j9', filename: 'r.pdf', status: 'review_ready', created_at: '2026-10-07T10:00:00Z' }]),
    )
    renderPage()
    await screen.findByText('r.pdf')
    expect(within(history()).getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/admin/import/jobs/j9/review')
  })

  it('offers Retry in the history only on jobs with a failed or blocked task', async () => {
    api.import.listJobs.mockResolvedValue(listing([
      { id: 'q', filename: 'queued.pdf', status: 'queued', tasks_failed: 0, created_at: daysAgo(1) },
      { id: 'r', filename: 'ready.pdf', status: 'review_ready', tasks_failed: 0, created_at: daysAgo(1) },
      { id: 's', filename: 'section.pdf', status: 'review_ready', tasks_failed: 2, created_at: daysAgo(1) },
      { id: 'f', filename: 'failed.pdf', status: 'failed', tasks_failed: 1, created_at: daysAgo(1) },
    ]))
    renderPage()
    await screen.findAllByText('section.pdf')
    const row = name => within(history()).getByText(name).closest('tr')
    expect(within(row('queued.pdf')).queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(within(row('ready.pdf')).queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(within(row('failed.pdf')).getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    await userEvent.click(within(row('section.pdf')).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(api.import.retryJob).toHaveBeenCalledWith('s'))
  })

  describe('the upload queue', () => {
    let xhrs
    let fetchMock
    let nextJob

    class FakeXhr {
      constructor() { this.upload = {}; this.aborted = false; xhrs.push(this) }
      open(method, url) { this.method = method; this.url = url }
      send(form) { this.form = form }
      abort() { this.aborted = true }
    }

    const jsonRes = (status, body) => ({ ok: status < 400, status, json: async () => body })

    beforeEach(() => {
      xhrs = []
      nextJob = 0
      vi.stubGlobal('XMLHttpRequest', FakeXhr)
      fetchMock = vi.fn(async (url, opts) => {
        if (url === '/api/import/uploads') {
          nextJob += 1
          return jsonRes(201, { job_id: `n${nextJob}`, url: 'https://s3.test/bucket', fields: { key: `ingest/n${nextJob}/source.pdf`, 'Content-Type': 'application/pdf' } })
        }
        if (opts.method === 'DELETE') return { ok: true, status: 204 }
        return jsonRes(200, { status: 'queued' })
      })
      vi.stubGlobal('fetch', fetchMock)
    })
    afterEach(() => vi.unstubAllGlobals())

    const pdf = name => new File(['%PDF'], name, { type: 'application/pdf', lastModified: 1 })
    const pick = async (container, files, testid = 'pick-files') =>
      userEvent.upload(container.querySelector(`[data-testid=${testid}]`), files, { applyAccept: false })
    const calls = () => fetchMock.mock.calls.map(([url, opts]) => `${opts.method} ${url}`)

    it('shows per-file progress, then queues the job and refreshes the list', async () => {
      const { container } = renderPage()
      await screen.findAllByText('second.pdf')
      const file = pdf('new.pdf')
      await pick(container, file)

      await waitFor(() => expect(xhrs).toHaveLength(1))
      const [xhr] = xhrs
      expect(xhr.method).toBe('POST')
      expect(xhr.url).toBe('https://s3.test/bucket')
      expect([...xhr.form.keys()]).toEqual(['key', 'Content-Type', 'file'])
      expect(xhr.form.get('file')).toBe(file)
      expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ filename: 'new.pdf', size: file.size })
      expect(screen.getByRole('status')).toHaveTextContent('1 PDF added to the upload queue.')

      act(() => xhr.upload.onprogress({ lengthComputable: true, loaded: 25, total: 100 }))
      expect(await screen.findByLabelText('Upload progress of new.pdf')).toHaveAttribute('value', '25')
      expect(screen.getByText(/Uploading 25%/)).toBeInTheDocument()

      api.import.listJobs.mockResolvedValue(listing([
        { id: 'n1', filename: 'new.pdf', status: 'queued', created_at: '2026-10-08T10:00:00Z' }, ...JOBS,
      ]))
      xhr.status = 204
      act(() => xhr.onload())
      await waitFor(() => expect(calls()).toEqual(['POST /api/import/uploads', 'POST /api/import/jobs/n1/uploaded']))
      expect(await within(board()).findByText('new.pdf')).toBeInTheDocument()
      expect(screen.queryByLabelText('Upload progress of new.pdf')).not.toBeInTheDocument()
    })

    it('uploads three at a time and takes more files while those run', async () => {
      const { container } = renderPage()
      await screen.findAllByText('second.pdf')
      await pick(container, [pdf('1.pdf'), pdf('2.pdf'), pdf('3.pdf'), pdf('4.pdf')])
      await waitFor(() => expect(xhrs).toHaveLength(3))
      expect(screen.getAllByTestId('upload-row')).toHaveLength(4)
      expect(screen.getByText(/Waiting to upload/)).toBeInTheDocument()

      // More files can be added straight away; an exact duplicate is skipped.
      await pick(container, [pdf('5.pdf'), pdf('1.pdf')])
      expect(screen.getByRole('status')).toHaveTextContent('1 PDF added to the upload queue · 1 duplicate skipped (already queued).')
      expect(screen.getAllByTestId('upload-row')).toHaveLength(5)
      expect(xhrs).toHaveLength(3)

      // One finishes: the next waiting file starts.
      xhrs[0].status = 204
      act(() => xhrs[0].onload())
      await waitFor(() => expect(xhrs).toHaveLength(4))
      expect(xhrs[3].form.get('file').name).toBe('4.pdf')
    })

    it('removes a waiting file, and stops an upload in flight (cancelling its job)', async () => {
      const { container } = renderPage()
      await screen.findAllByText('second.pdf')
      await pick(container, [pdf('1.pdf'), pdf('2.pdf'), pdf('3.pdf'), pdf('4.pdf')])
      await waitFor(() => expect(xhrs).toHaveLength(3))
      await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
      expect(screen.getAllByTestId('upload-row')).toHaveLength(3)

      await userEvent.click(screen.getAllByRole('button', { name: 'Stop' })[0])
      await waitFor(() => expect(calls()).toContain('DELETE /api/import/jobs/n1'))
      expect(xhrs[0].aborted).toBe(true)
      await waitFor(() => expect(screen.getAllByTestId('upload-row')).toHaveLength(2))
    })

    it('keeps a failed upload with its error, cancels its job, and can retry it', async () => {
      const { container } = renderPage()
      await screen.findAllByText('second.pdf')
      await pick(container, pdf('bad.pdf'))
      await waitFor(() => expect(xhrs).toHaveLength(1))
      xhrs[0].status = 403
      act(() => xhrs[0].onload())
      expect(await screen.findByText(/Upload failed: Upload to storage failed/)).toBeInTheDocument()
      expect(calls()).toEqual(['POST /api/import/uploads', 'DELETE /api/import/jobs/n1'])

      await userEvent.click(screen.getByRole('button', { name: 'Retry upload' }))
      await waitFor(() => expect(xhrs).toHaveLength(2))
    })

    it('shows the API error of a refused upload', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 403, json: async () => ({ detail: 'Only PDF files are accepted' }) })))
      const { container } = renderPage()
      await screen.findAllByText('second.pdf')
      await pick(container, pdf('a.pdf'))
      expect(await screen.findByText(/Only PDF files are accepted/)).toBeInTheDocument()
    })

    it('takes the PDFs out of a picked folder and says what it ignored', async () => {
      const { container } = renderPage()
      await screen.findAllByText('second.pdf')
      await pick(container, [pdf('b.pdf'), new File(['x'], 'notes.txt', { type: 'text/plain' }), pdf('a.PDF')], 'pick-folder')
      expect(screen.getByRole('status')).toHaveTextContent('2 PDFs added to the upload queue · 1 non-PDF file ignored.')
      await waitFor(() => expect(xhrs).toHaveLength(2))
      // Queued in name order.
      expect(xhrs.map(x => x.form.get('file').name)).toEqual(['a.PDF', 'b.pdf'])
    })
  })

  describe('polling and worker state', () => {
    afterEach(() => vi.useRealTimers())

    async function tick(ms = POLL_MS) {
      await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
    }

    it('polls every 3 s while a job is queued or running, then slows down', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      renderPage()
      await screen.findAllByText('second.pdf')
      expect(api.import.listJobs).toHaveBeenCalledTimes(1)

      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(2)

      // The job finishes: the next poll returns nothing active, then polling slows to IDLE_POLL_MS.
      api.import.listJobs.mockResolvedValue(listing([{ ...JOBS[0], status: 'review_ready' }]))
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(3)
      await tick()
      await tick()
      expect(api.import.listJobs).toHaveBeenCalledTimes(3)
      await tick(IDLE_POLL_MS)
      expect(api.import.listJobs).toHaveBeenCalledTimes(4)
    })

    it('lists jobs that finished while the page was open, linked to their review', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      renderPage()
      await screen.findAllByText('second.pdf')
      api.import.listJobs.mockResolvedValue(listing([{ ...JOBS[0], status: 'review_ready' }, JOBS[1]]))
      await tick()
      const done = await screen.findByRole('region', { name: 'Finished while you were here' })
      expect(within(done).getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/admin/import/jobs/j2/review')
    })

    it('stops polling on unmount', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const { unmount } = renderPage()
      await screen.findAllByText('second.pdf')
      const before = api.import.listJobs.mock.calls.length
      unmount()
      await tick()
      await tick(IDLE_POLL_MS)
      expect(api.import.listJobs).toHaveBeenCalledTimes(before)
    })

    it('warns "worker offline" when jobs are waiting and the heartbeat is stale', async () => {
      api.import.listJobs.mockResolvedValue(listing(JOBS, false))
      renderPage()
      expect(await screen.findByRole('alert')).toHaveTextContent('Worker offline')
      expect(within(board()).getByText('Worker offline')).toBeInTheDocument()
    })

    it('shows no offline warning while the worker is alive, or when nothing is waiting', async () => {
      renderPage()
      await screen.findAllByText('second.pdf')
      expect(screen.queryByText(/worker offline/i)).not.toBeInTheDocument()
    })

    it('shows no offline warning when nothing is waiting', async () => {
      api.import.listJobs.mockResolvedValue(listing([JOBS[1]], false))
      renderPage()
      await screen.findByText('first.pdf')
      expect(screen.queryByText(/worker offline/i)).not.toBeInTheDocument()
    })
  })
})
