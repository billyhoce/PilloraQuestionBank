import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import AgeBadge from './AgeBadge'
import JobDetail from './JobDetail'
import { AWAITING_QUERY } from './jobAge'
import { CANCELLABLE, STATUS_LABELS, canRetry, formatCreated } from './jobStatus'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// A search term is a job id (a UUID) or a paper id (digits); anything else is not searchable.
function parseJobSearch(term) {
  const t = term.trim()
  if (!t) return {}
  if (UUID_RE.test(t)) return { job_id: t.toLowerCase() }
  if (/^\d+$/.test(t)) return { paper_id: t }
  return null
}

// Every job, settled ones included, with search and filters. Unfiltered it shows `allJobs` (the
// page's own polled list); a filter fetches its own list, again whenever `version` moves.
export default function JobHistory({ allJobs, version, onRetry, onCancel }) {
  const [term, setTerm] = useState('')
  const [filter, setFilter] = useState({})
  const [awaiting, setAwaiting] = useState(false)
  const [unmatched, setUnmatched] = useState(false)
  const [filtered, setFiltered] = useState(null)
  const [error, setError] = useState(null)
  const [openId, setOpenId] = useState(null)

  const statusFilter = awaiting ? AWAITING_QUERY : undefined
  const query = useMemo(() => (unmatched ? { ...filter, unmatched_answers: true } : filter), [filter, unmatched])
  const filtering = !!statusFilter || Object.keys(query).length > 0

  useEffect(() => {
    if (!filtering) return undefined
    let live = true
    api.import.listJobs(statusFilter, query)
      .then(res => { if (live) { setFiltered(res.jobs); setError(null) } })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [filtering, statusFilter, query, version])

  const jobs = filtering ? filtered : allJobs
  const parsed = parseJobSearch(term)

  function handleSearch(e) {
    e.preventDefault()
    if (parsed) {
      setFiltered(null)
      setFilter(parsed)
    }
  }

  function clearSearch() {
    setTerm('')
    setFilter({})
  }

  const toggle = setter => e => {
    setFiltered(null)
    setter(e.target.checked)
  }

  return (
    <section aria-labelledby="job-history" className="mt-8">
      <h2 id="job-history" className="text-lg font-semibold text-gray-800 mb-2">All jobs</h2>
      <form onSubmit={handleSearch} className="flex items-center gap-2 mb-2">
        <input
          type="search"
          aria-label="Search jobs by job id or paper id"
          placeholder="Job id or paper id"
          value={term}
          onChange={e => setTerm(e.target.value)}
          className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
        />
        <button type="submit" disabled={!parsed} className="text-sm text-blue-600 hover:underline disabled:text-gray-400 disabled:no-underline">
          Search
        </button>
        {(filter.job_id || filter.paper_id) && (
          <button type="button" onClick={clearSearch} className="text-sm text-gray-600 hover:underline">
            Clear
          </button>
        )}
      </form>
      <div className="flex gap-4 mb-2">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={awaiting} onChange={toggle(setAwaiting)} />
          Awaiting review
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={unmatched} onChange={toggle(setUnmatched)} />
          Unmatched answers
        </label>
      </div>
      {parsed === null && (
        <p className="mb-2 text-xs text-gray-500">Enter a job id (UUID) or a numeric paper id.</p>
      )}
      <ErrorBanner message={error} />

      {jobs == null ? (
        error ? null : <Spinner />
      ) : jobs.length === 0 ? (
        <p className="text-sm text-gray-500">{filtering ? 'No jobs match.' : 'No import jobs yet.'}</p>
      ) : (
        <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-sm bg-white border border-gray-200 rounded">
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
                    {job.status === 'failed' && job.error && (
                      <div className="text-xs text-red-600 break-words">{job.error}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {formatCreated(job.created_at)}
                    <AgeBadge job={job} />
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {job.status === 'review_ready' && (
                      <Link to={`/admin/import/jobs/${job.id}/review`} className="text-blue-700 hover:underline mr-3">
                        Review
                      </Link>
                    )}
                    {canRetry(job) && (
                      <button type="button" onClick={() => onRetry(job)} className="text-blue-600 hover:underline mr-3">
                        Retry
                      </button>
                    )}
                    {CANCELLABLE.includes(job.status) && (
                      <button type="button" onClick={() => onCancel(job)} className="text-red-600 hover:underline">
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
                {openId === job.id && (
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <td colSpan={4} className="px-3 py-2">
                      <JobDetail jobId={job.id} version={version} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </section>
  )
}
