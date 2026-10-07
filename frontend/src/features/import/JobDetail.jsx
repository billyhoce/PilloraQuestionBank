import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'

function formatDuration(ms) {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

// Every task of one job with its status, duration, warnings and reason/error.
// `version` changes whenever the list refreshed, so an open detail stays live.
export default function JobDetail({ jobId, version }) {
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    api.import.getJob(jobId)
      .then(j => { if (live) { setJob(j); setError(null) } })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobId, version])

  if (error) return <ErrorBanner message={error} />
  if (!job) return <p className="text-xs text-gray-500">Loading tasks…</p>
  return (
    <table className="w-full text-xs" aria-label={`Tasks of ${job.filename}`}>
      <thead>
        <tr className="text-left text-gray-500">
          <th className="py-1 pr-2 font-medium">Stage</th>
          <th className="py-1 pr-2 font-medium">Section</th>
          <th className="py-1 pr-2 font-medium">Status</th>
          <th className="py-1 pr-2 font-medium">Duration</th>
          <th className="py-1 pr-2 font-medium">Warnings</th>
          <th className="py-1 font-medium">Reason / error</th>
        </tr>
      </thead>
      <tbody>
        {job.tasks.map(t => (
          <tr key={t.id} className="border-t border-gray-100 align-top">
            <td className="py-1 pr-2">{t.stage}</td>
            <td className="py-1 pr-2">{t.section ?? '—'}</td>
            <td className="py-1 pr-2">{t.status}{t.needs_review ? ' (needs review)' : ''}</td>
            <td className="py-1 pr-2 whitespace-nowrap">{formatDuration(t.duration_ms)}</td>
            <td className="py-1 pr-2">
              {t.warnings?.length ? (
                <ul className="list-disc pl-4">{t.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
              ) : '—'}
            </td>
            <td className="py-1 break-words">{t.error || t.reason || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
