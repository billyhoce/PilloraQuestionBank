import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import UploadDropZone from './UploadDropZone'

// Statuses a job can still be cancelled from (mirrors the server).
const CANCELLABLE = ['queued', 'running', 'review_ready', 'failed']

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
  const [listError, setListError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      setJobs(await api.import.listJobs())
      setListError(null)
    } catch (e) {
      setListError(e.message)
    }
  }, [])

  useEffect(() => {
    let live = true
    api.import.listJobs()
      .then(list => { if (live) setJobs(list) })
      .catch(e => { if (live) setListError(e.message) })
    return () => { live = false }
  }, [])

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

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
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
              <th className="px-3 py-2 font-medium">Created</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {jobs.map(job => (
              <tr key={job.id} className="border-b border-gray-100 last:border-0">
                <td className="px-3 py-2 break-all">{job.filename}</td>
                <td className="px-3 py-2">{STATUS_LABELS[job.status] ?? job.status}</td>
                <td className="px-3 py-2 whitespace-nowrap">{formatCreated(job.created_at)}</td>
                <td className="px-3 py-2 text-right">
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
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
