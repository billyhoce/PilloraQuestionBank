import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import UploadDropZone from './UploadDropZone'
import JobDetail from './JobDetail'

// Statuses a job can still be cancelled from (mirrors the server).
const CANCELLABLE = ['queued', 'running', 'review_ready', 'failed']

// Queued jobs count as active: with a live worker they flip to running soon.
const ACTIVE = ['queued', 'running']
// Jobs retry applies to (the server refuses cancelled/confirmed/expired).
const RETRYABLE = ['queued', 'running', 'review_ready', 'failed']
export const POLL_MS = 3000

const STATUS_LABELS = {
  queued: 'Queued',
  running: 'Running',
  review_ready: 'Ready for review',
  failed: 'Failed',
  confirmed: 'Confirmed',
  cancelled: 'Cancelled',
  expired: 'Expired',
}

function formatCreated(iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

export default function AutoImport() {
  const [jobs, setJobs] = useState(null)
  const [worker, setWorker] = useState({ alive: true, ageS: null })
  const [version, setVersion] = useState(0)
  const [openId, setOpenId] = useState(null)
  const [listError, setListError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  const applyList = useCallback(res => {
    setJobs(res.jobs)
    setWorker({ alive: res.workerAlive !== false, ageS: res.heartbeatAgeS ?? null })
    setVersion(v => v + 1)
    setListError(null)
  }, [])

  const refresh = useCallback(async () => {
    try {
      applyList(await api.import.listJobs())
    } catch (e) {
      setListError(e.message)
    }
  }, [applyList])

  useEffect(() => {
    let live = true
    api.import.listJobs()
      .then(res => { if (live) applyList(res) })
      .catch(e => { if (live) setListError(e.message) })
    return () => { live = false }
  }, [applyList])

  // Poll every POLL_MS while any job is queued or running; stops when none is, and on unmount.
  const anyActive = !!jobs && jobs.some(j => ACTIVE.includes(j.status))
  useEffect(() => {
    if (!anyActive) return undefined
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [anyActive, refresh])

  async function handleUpload(files) {
    setUploading(true)
    setUploadError(null)
    try {
      // One job per PDF.
      for (const file of files) await api.import.createJob(file)
    } catch (e) {
      setUploadError(e.message)
    } finally {
      setUploading(false)
      refresh()
    }
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

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <UploadDropZone
        compact
        onUpload={handleUpload}
        loading={uploading}
        error={uploadError}
        loadingMessage="Uploading…"
        prompt="Drag & drop PDF(s) to auto-detect questions"
      />

      <div className="flex items-center justify-between mt-6 mb-2">
        <h2 className="text-lg font-semibold text-gray-800">Import jobs</h2>
        <button type="button" onClick={refresh} className="text-sm text-blue-600 hover:underline">
          Refresh
        </button>
      </div>
      <ErrorBanner message={listError} />
      {anyActive && !worker.alive && (
        <p role="alert" className="mb-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          Worker offline — queued jobs will not progress until the import worker is running.
        </p>
      )}

      {jobs === null && !listError ? (
        <Spinner />
      ) : jobs && jobs.length === 0 ? (
        <p className="text-sm text-gray-500">No import jobs yet.</p>
      ) : jobs ? (
        <table className="w-full text-sm bg-white border border-gray-200 rounded">
          <thead>
            <tr className="text-left text-gray-500 border-b border-gray-200">
              <th className="px-3 py-2 font-medium">File</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Progress</th>
              <th className="px-3 py-2 font-medium">Created</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {jobs.map(job => (
              <Fragment key={job.id}>
                <tr className="border-b border-gray-100 last:border-0 align-top">
                  <td className="px-3 py-2 break-all">
                    <button
                      type="button"
                      aria-expanded={openId === job.id}
                      onClick={() => setOpenId(openId === job.id ? null : job.id)}
                      className="text-left text-blue-700 hover:underline"
                    >
                      {job.filename}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <div>{STATUS_LABELS[job.status] ?? job.status}</div>
                    {ACTIVE.includes(job.status) && !worker.alive && (
                      <div className="text-xs text-amber-700">Worker offline</div>
                    )}
                    {job.needs_review && <div className="text-xs text-amber-700">Needs review</div>}
                  </td>
                  <td className="px-3 py-2 min-w-40">
                    {job.stage && <div className="text-xs text-gray-600">{job.stage}</div>}
                    {job.tasks_total > 0 && (
                      <>
                        <progress
                          className="w-full h-2"
                          value={job.tasks_done}
                          max={job.tasks_total}
                          aria-label={`Progress of ${job.filename}`}
                        />
                        <div className="text-xs text-gray-500">{job.tasks_done}/{job.tasks_total} tasks</div>
                      </>
                    )}
                    {job.warnings_count > 0 && (
                      <div className="text-xs text-amber-700">{job.warnings_count} warning{job.warnings_count === 1 ? '' : 's'}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{formatCreated(job.created_at)}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {job.status === 'review_ready' && (
                      <Link
                        to={`/admin/import/jobs/${job.id}/review`}
                        className="text-blue-700 hover:underline mr-3"
                      >
                        Review
                      </Link>
                    )}
                    {RETRYABLE.includes(job.status) && (
                      <button
                        type="button"
                        onClick={() => handleRetry(job)}
                        className="text-blue-600 hover:underline mr-3"
                      >
                        Retry
                      </button>
                    )}
                    {CANCELLABLE.includes(job.status) && (
                      <button
                        type="button"
                        onClick={() => handleCancel(job)}
                        className="text-red-600 hover:underline"
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
                {openId === job.id && (
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <td colSpan={5} className="px-3 py-2">
                      <JobDetail jobId={job.id} version={version} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
