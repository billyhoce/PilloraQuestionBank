import { useEffect, useRef, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import AgeBadge from './AgeBadge'
import { unansweredWarning } from './answerCoverage'
import { useReferenceData } from './importMetadata'
import MatchDialog from './MatchDialog'
import useReviewQueue from './useReviewQueue'
import { describeMetadata, matchState, needsPartner } from './reviewQueueText'

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

const TONE = { green: 'text-green-700', amber: 'text-amber-700' }
const OUTCOME = { confirmed: 'Confirmed', skipped: 'Skipped', attached: 'Attached' }

function PaperLine({ paper, refs, onMatch }) {
  const meta = describeMetadata(paper, refs)
  const match = matchState(paper)
  const decided = paper.status !== 'pending'
  // Answers are all or none: a question paper whose own booklet answered only some questions.
  const partly = paper.role !== 'answer_only' && paper.answer_coverage === 'partial' ? unansweredWarning(paper.unanswered) : null
  return (
    <li className={`text-xs ${decided ? 'text-gray-400' : 'text-gray-700'}`}>
      <span className={`inline-block rounded px-1.5 py-0.5 mr-1.5 font-medium ${paper.role === 'answer_only' ? 'bg-green-100 text-green-800' : 'bg-blue-100 text-blue-800'}`}>
        {paper.role === 'answer_only' ? 'Answers' : 'Questions'} {paper.key}
      </span>
      {meta.text || <span className="italic">No details read from the cover</span>}
      {decided ? (
        <span className="ml-1.5">— {OUTCOME[paper.status] ?? paper.status}</span>
      ) : (
        <>
          {meta.missing.length > 0 && meta.text && <span className="ml-1.5 text-amber-700">(missing {meta.missing.join(', ')})</span>}
          {match && <span className={`ml-1.5 ${TONE[match.tone]}`}>· {match.text}</span>}
          {partly && <span className="ml-1.5 text-amber-700">· {partly}</span>}
          {needsPartner(paper) && (
            <button
              type="button" aria-label={`Match ${paper.key}`} onClick={() => onMatch(paper)}
              className="ml-2 rounded border border-blue-300 px-1.5 py-0.5 text-blue-700 hover:bg-blue-50"
            >
              Match
            </button>
          )}
        </>
      )}
    </li>
  )
}

// Jobs the worker has finished, waiting for an admin to check and confirm them. Polled (through
// the import layout) so newly finished jobs appear on their own; the oldest waits at the top.
export default function ReviewQueuePage() {
  const outlet = useOutletContext()
  // Rendered outside the import layout (tests), it polls for itself.
  const own = useReviewQueue({ enabled: !outlet?.reviewQueue })
  const { jobs, error, checkedAt, refresh } = outlet?.reviewQueue ?? own
  const refs = useReferenceData()
  const [unmatchedOnly, setUnmatchedOnly] = useState(false)
  // The paper line whose "Match this paper" popup is open: { jobId, paper }.
  const [matching, setMatching] = useState(null)
  const matched = () => { setMatching(null); refresh() }

  // Jobs that arrived after the page first loaded get a "New" tag.
  const initial = useRef(null)
  const [fresh, setFresh] = useState(() => new Set())
  useEffect(() => {
    if (!jobs) return
    if (initial.current === null) {
      initial.current = new Set(jobs.map(j => j.id))
      return
    }
    const arrived = jobs.filter(j => !initial.current.has(j.id)).map(j => j.id)
    if (arrived.length) setFresh(f => new Set([...f, ...arrived]))
  }, [jobs])

  if (jobs === null) return error ? <div className="max-w-5xl mx-auto px-4 py-6"><ErrorBanner message={error} /></div> : <Spinner />

  const unmatched = j => (j.papers ?? []).some(p => p.role === 'answer_only' && p.status === 'pending' && !p.linked)
  const shown = [...jobs]
    .filter(j => !unmatchedOnly || unmatched(j))
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3">
        <h1 className="text-lg font-semibold text-gray-800">Ready for review</h1>
        <span className="text-sm text-gray-500">{plural(jobs.length, 'job')}, oldest first</span>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={unmatchedOnly} onChange={e => setUnmatchedOnly(e.target.checked)} />
          Only jobs with unmatched answers
        </label>
        {checkedAt && (
          <span className="ml-auto text-xs text-gray-400" title="This list refreshes on its own">
            Checked {checkedAt.toLocaleTimeString()}
          </span>
        )}
      </div>
      <ErrorBanner message={error} />

      {shown.length === 0 ? (
        <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded px-3 py-4">
          {jobs.length === 0
            ? 'Nothing to review. Jobs appear here as soon as the worker finishes them — no need to refresh.'
            : 'No job has unmatched answers.'}
        </p>
      ) : (
        <ul aria-label="Jobs ready for review" className="space-y-2">
          {shown.map(job => {
            const papers = job.papers ?? []
            const pending = papers.filter(p => p.status === 'pending').length
            return (
              <li key={job.id} data-testid="review-card" className="bg-white border border-gray-200 rounded px-4 py-3 flex gap-4 items-start">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2">
                    <Link to={`/admin/import/jobs/${job.id}/review`} className="text-sm font-medium text-blue-700 hover:underline break-all">
                      {job.filename}
                    </Link>
                    {fresh.has(job.id) && <span className="rounded bg-blue-600 text-white text-[10px] px-1.5 py-0.5 uppercase tracking-wide">New</span>}
                    <AgeBadge job={job} />
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {job.page_count ? `${plural(job.page_count, 'page')} · ` : ''}
                    {papers.length ? `${plural(papers.length, 'paper')}${pending < papers.length ? `, ${pending} still to decide` : ''}` : 'No paper found'}
                    {job.warnings_count > 0 && <span className="text-amber-700"> · {plural(job.warnings_count, 'warning')}</span>}
                    {job.needs_review && <span className="text-amber-700"> · Pages flagged for a closer look</span>}
                  </div>
                  {papers.length > 0 && <ul className="mt-1.5 space-y-1">{papers.map(p => (
                    <PaperLine key={p.key} paper={p} refs={refs} onMatch={paper => setMatching({ jobId: job.id, paper })} />
                  ))}</ul>}
                </div>
                <Link
                  to={`/admin/import/jobs/${job.id}/review`}
                  className="shrink-0 bg-blue-600 hover:bg-blue-700 text-white rounded px-3 py-1.5 text-sm font-medium"
                >
                  Review
                </Link>
              </li>
            )
          })}
        </ul>
      )}
      {matching && (
        // The queue has no page images, so the popup shows no preview of the paper's own pages;
        // its fields come from the summary.
        <MatchDialog
          jobId={matching.jobId} paperKey={matching.paper.key} role={matching.paper.role} metadata={matching.paper}
          extractedSchool={matching.paper.extracted_school ?? null}
          refs={refs} ownPreview={null}
          onPaired={matched} onAttached={matched} onClose={() => setMatching(null)}
        />
      )}
    </div>
  )
}
