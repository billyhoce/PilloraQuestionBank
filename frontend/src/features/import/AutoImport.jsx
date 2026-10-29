import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import AgeBadge from './AgeBadge'
import JobDetail from './JobDetail'
import JobHistory from './JobHistory'
import PdfDropZone from './PdfDropZone'
import PipelineStepper from './PipelineStepper'
import { jobPhase, phaseCaption } from './pipelinePhases'
import { ACTIVE, CANCELLABLE, IN_PIPELINE, canRetry } from './jobStatus'
import { useUploadQueue } from './uploadQueueContext'
import usePoll from './usePoll'

// While anything is uploading or processing the board refreshes every POLL_MS; otherwise every
// IDLE_POLL_MS, so a job another admin drops still turns up.
export const POLL_MS = 3000
export const IDLE_POLL_MS = 15000

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

function formatSize(bytes) {
  if (bytes == null) return ''
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const rowCls = 'grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_auto_auto] gap-x-4 gap-y-1 items-center px-3 py-2'
const linkBtn = 'text-sm hover:underline disabled:opacity-50'

// A file still in the browser's upload queue.
function UploadRow({ item, onCancel, onRetry, onDismiss }) {
  const pct = Math.round(item.progress * 100)
  const caption = item.status === 'waiting' ? 'Waiting to upload'
    : item.status === 'failed' ? `Upload failed: ${item.error}`
      : `Uploading ${pct}%`
  return (
    <li data-testid="upload-row" className={rowCls}>
      <div className="min-w-0">
        <div className="text-sm font-medium text-gray-800 break-all">{item.name}</div>
        <div className={`text-xs ${item.status === 'failed' ? 'text-red-600' : 'text-gray-500'}`}>
          {caption} · {formatSize(item.size)}
        </div>
        {item.status === 'uploading' && (
          <progress className="w-full h-1.5" value={pct} max={100} aria-label={`Upload progress of ${item.name}`} />
        )}
      </div>
      <PipelineStepper current={0} state={item.status === 'failed' ? 'failed' : item.status === 'waiting' ? 'waiting' : 'active'} label={`Steps of ${item.name}`} />
      <div className="text-right whitespace-nowrap space-x-3">
        {item.status === 'failed' ? (
          <>
            <button type="button" onClick={() => onRetry(item.id)} className={`${linkBtn} text-blue-600`}>Retry upload</button>
            <button type="button" onClick={() => onDismiss(item.id)} className={`${linkBtn} text-gray-600`}>Remove</button>
          </>
        ) : (
          <button type="button" onClick={() => onCancel(item.id)} className={`${linkBtn} text-red-600`}>
            {item.status === 'waiting' ? 'Remove' : 'Stop'}
          </button>
        )}
      </div>
    </li>
  )
}

// A job on the server that is still processing, or stopped in the pipeline.
function JobRow({ job, workerAlive, open, onToggle, onRetry, onCancel, version }) {
  const phase = jobPhase(job)
  const orphanUpload = job.status === 'awaiting_upload'
  return (
    <li data-testid="job-row" className="border-b border-gray-100 last:border-0">
      <div className={rowCls}>
        <div className="min-w-0">
          <button
            type="button"
            aria-expanded={open}
            onClick={onToggle}
            className="text-left text-sm font-medium text-blue-700 hover:underline break-all"
          >
            {job.filename}
          </button>
          <div className={`text-xs ${phase.state === 'failed' ? 'text-red-600' : 'text-gray-500'}`}>
            {orphanUpload ? 'Upload not finished (started in another tab or session)' : phaseCaption(job)}
            {job.page_count ? ` · ${plural(job.page_count, 'page')}` : ''}
            {job.warnings_count > 0 && <span className="text-amber-700"> · {plural(job.warnings_count, 'warning')}</span>}
            <AgeBadge job={job} />
          </div>
          {phase.state === 'failed' && job.error && <div className="text-xs text-red-600 break-words">{job.error}</div>}
          {ACTIVE.includes(job.status) && !workerAlive && <div className="text-xs text-amber-700">Worker offline</div>}
          {job.status === 'running' && job.tasks_total > 0 && (
            <progress className="w-full h-1.5" value={job.tasks_done} max={job.tasks_total} aria-label={`Progress of ${job.filename}`} />
          )}
        </div>
        <PipelineStepper current={phase.current} state={phase.state} label={`Steps of ${job.filename}`} />
        <div className="text-right whitespace-nowrap space-x-3">
          {canRetry(job) && (
            <button type="button" onClick={() => onRetry(job)} className={`${linkBtn} text-blue-600`}>Retry</button>
          )}
          {CANCELLABLE.includes(job.status) && (
            <button type="button" onClick={() => onCancel(job)} className={`${linkBtn} text-red-600`}>Cancel</button>
          )}
        </div>
      </div>
      {open && (
        <div className="px-3 pb-3 bg-gray-50">
          <JobDetail jobId={job.id} version={version} />
        </div>
      )}
    </li>
  )
}

function Count({ n, label, tone = 'text-gray-700' }) {
  return <span className={`text-sm ${tone}`}><span className="font-semibold">{n}</span> {label}</span>
}

export default function AutoImport() {
  const uploads = useUploadQueue()
  const [jobs, setJobs] = useState(null)
  const [workerAlive, setWorkerAlive] = useState(true)
  const [version, setVersion] = useState(0)
  const [listError, setListError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [openId, setOpenId] = useState(null)
  // Jobs that finished processing while this page was open: a shortcut to review them.
  const [finished, setFinished] = useState([])
  const seenInPipeline = useRef(new Set())

  const apply = useCallback(res => {
    const done = []
    for (const j of res.jobs) {
      if (IN_PIPELINE.includes(j.status) && j.status !== 'failed') seenInPipeline.current.add(j.id)
      else if (seenInPipeline.current.has(j.id)) {
        seenInPipeline.current.delete(j.id)
        if (j.status === 'review_ready') done.push(j)
      }
    }
    if (done.length) setFinished(f => [...done, ...f.filter(x => !done.some(d => d.id === x.id))])
    setJobs(res.jobs)
    setWorkerAlive(res.workerAlive !== false)
    setVersion(v => v + 1)
    setListError(null)
  }, [])

  const refresh = useCallback(async () => {
    try {
      apply(await api.import.listJobs())
    } catch (e) {
      setListError(e.message)
    }
  }, [apply])

  // First load, and again each time an upload finishes (its job is then queued on the server).
  const completed = uploads?.completed ?? 0
  useEffect(() => {
    let live = true
    api.import.listJobs()
      .then(res => { if (live) apply(res) })
      .catch(e => { if (live) setListError(e.message) })
    return () => { live = false }
  }, [apply, completed])

  const items = uploads?.items ?? []
  const localJobIds = new Set(items.map(it => it.jobId).filter(Boolean))
  const board = (jobs ?? []).filter(j => IN_PIPELINE.includes(j.status) && !localJobIds.has(j.id))
  const busy = items.some(it => it.status !== 'failed') || board.some(j => ACTIVE.includes(j.status) || j.status === 'awaiting_upload')
  usePoll(refresh, busy ? POLL_MS : IDLE_POLL_MS)

  function handleFiles({ pdfs, ignored }) {
    const { added, duplicates } = pdfs.length ? uploads.add(pdfs) : { added: 0, duplicates: 0 }
    const parts = []
    if (added) parts.push(`${plural(added, 'PDF')} added to the upload queue`)
    if (duplicates) parts.push(`${plural(duplicates, 'duplicate')} skipped (already queued)`)
    if (ignored) parts.push(`${plural(ignored, 'non-PDF file')} ignored`)
    setNotice(parts.length ? `${parts.join(' · ')}.` : 'No PDFs found.')
  }

  async function handleCancel(job) {
    if (!window.confirm(`Cancel the import of "${job.filename}"?`)) return
    try {
      await api.import.cancelJob(job.id)
    } catch (e) {
      setListError(e.message)
    }
    refresh()
  }

  async function handleRetry(job) {
    try {
      await api.import.retryJob(job.id)
    } catch (e) {
      setListError(e.message)
    }
    refresh()
  }

  const uploadingN = items.filter(it => it.status !== 'failed').length
  const queuedN = board.filter(j => j.status === 'queued').length
  const runningN = board.filter(j => j.status === 'running').length
  const failedN = board.filter(j => j.status === 'failed').length + items.filter(it => it.status === 'failed').length
  const readyN = (jobs ?? []).filter(j => j.status === 'review_ready').length
  const waitingUploads = items.filter(it => it.status === 'waiting').length

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <PdfDropZone onFiles={handleFiles} />
      {notice && <p role="status" className="mt-2 text-sm text-gray-600">{notice}</p>}

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mt-6 mb-2">
        <h2 className="text-lg font-semibold text-gray-800 mr-2">Processing</h2>
        <Count n={uploadingN} label="uploading" />
        <Count n={queuedN} label="queued" />
        <Count n={runningN} label="running" />
        <Count n={failedN} label="failed" tone={failedN ? 'text-red-700' : 'text-gray-700'} />
        <Link to="/admin/import/review" className="text-sm text-blue-700 hover:underline">
          {plural(readyN, 'job')} ready for review →
        </Link>
        {waitingUploads > 1 && (
          <button type="button" onClick={() => uploads.cancelWaiting()} className="ml-auto text-sm text-gray-600 hover:underline">
            Remove {waitingUploads} waiting uploads
          </button>
        )}
      </div>

      <ErrorBanner message={listError} />
      {busy && !workerAlive && board.some(j => ACTIVE.includes(j.status)) && (
        <p role="alert" className="mb-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          Worker offline — queued jobs will not progress until the import worker is running.
        </p>
      )}

      {jobs === null && !listError ? (
        <Spinner />
      ) : items.length + board.length === 0 ? (
        <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded px-3 py-4">
          Nothing is processing. Drop PDFs above to start; finished jobs move to the review queue.
        </p>
      ) : (
        <ul aria-label="Jobs in progress" className="bg-white border border-gray-200 rounded divide-y divide-gray-100">
          {items.map(it => (
            <UploadRow key={it.id} item={it} onCancel={uploads.cancel} onRetry={uploads.retry} onDismiss={uploads.dismiss} />
          ))}
          {board.map(job => (
            <JobRow
              key={job.id}
              job={job}
              workerAlive={workerAlive}
              open={openId === job.id}
              onToggle={() => setOpenId(openId === job.id ? null : job.id)}
              onRetry={handleRetry}
              onCancel={handleCancel}
              version={version}
            />
          ))}
        </ul>
      )}

      {finished.length > 0 && (
        <section aria-label="Finished while you were here" className="mt-4 bg-green-50 border border-green-200 rounded px-3 py-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-green-900">Finished while you were here</h3>
            <button type="button" onClick={() => setFinished([])} className="text-xs text-green-900 hover:underline">Dismiss</button>
          </div>
          <ul className="mt-1 space-y-0.5">
            {finished.map(j => (
              <li key={j.id} className="text-sm text-green-900">
                <span className="break-all">{j.filename}</span>{' '}
                <Link to={`/admin/import/jobs/${j.id}/review`} className="text-blue-700 hover:underline">Review</Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <JobHistory allJobs={jobs} version={version} onRetry={handleRetry} onCancel={handleCancel} />
    </div>
  )
}
