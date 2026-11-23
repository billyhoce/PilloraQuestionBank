import { useEffect, useRef, useState } from 'react'
import { Link, useOutletContext } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import AgeBadge from './AgeBadge'
import { unansweredWarning } from './answerCoverage'
import { useReferenceData } from './importMetadata'
import MatchDialog from './MatchDialog'
import useReviewQueue from './useReviewQueue'
import { groupJobs, jobRole, suggestedPairs } from './queueGroups'
import { describeMetadata, matchState, mayBeAnswers, needsPartner } from './reviewQueueText'

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

const TONE = { green: 'text-green-700', amber: 'text-amber-700' }
const OUTCOME = { confirmed: 'Confirmed', skipped: 'Skipped', attached: 'Attached' }
const smallBtn = 'ml-2 rounded border px-1.5 py-0.5 disabled:opacity-50'

const reviewUrl = (jobId, key) => `/admin/import/jobs/${jobId}/review${key ? `?paper=${encodeURIComponent(key)}` : ''}`

function PaperLine({ paper, refs, onMatch, onAnswers, busy }) {
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
              className={`${smallBtn} border-blue-300 text-blue-700 hover:bg-blue-50`}
            >
              Match
            </button>
          )}
          {mayBeAnswers(paper) && (
            <button
              type="button" aria-label={`${paper.key} is an answer booklet`} disabled={busy} onClick={() => onAnswers(paper)}
              title="A solutions booklet read as questions: make its boxes answer boxes and pair it with its question paper"
              className={`${smallBtn} border-gray-300 text-gray-600 hover:bg-gray-50`}
            >
              This is an answer booklet
            </button>
          )}
        </>
      )}
    </li>
  )
}

// One job's part of a card: its file, its counts, and a line per proposed paper.
function JobBlock({ job, role, isNew, refs, onMatch, onAnswers, busy }) {
  const papers = job.papers ?? []
  const pending = papers.filter(p => p.status === 'pending').length
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-2">
        {role && <span className="text-[11px] font-medium uppercase tracking-wide text-gray-500">{role}</span>}
        <Link to={reviewUrl(job.id)} className="text-sm font-medium text-blue-700 hover:underline break-all">
          {job.filename}
        </Link>
        {isNew && <span className="rounded bg-blue-600 text-white text-[10px] px-1.5 py-0.5 uppercase tracking-wide">New</span>}
        <AgeBadge job={job} />
      </div>
      <div className="text-xs text-gray-500 mt-0.5">
        {job.page_count ? `${plural(job.page_count, 'page')} · ` : ''}
        {papers.length ? `${plural(papers.length, 'paper')}${pending < papers.length ? `, ${pending} still to decide` : ''}` : 'No paper found'}
        {job.warnings_count > 0 && <span className="text-amber-700"> · {plural(job.warnings_count, 'warning')}</span>}
        {job.needs_review && <span className="text-amber-700"> · Pages flagged for a closer look</span>}
      </div>
      {papers.length > 0 && <ul className="mt-1.5 space-y-1">{papers.map(p => (
        <PaperLine
          key={p.key} paper={p} refs={refs} busy={busy}
          onMatch={paper => onMatch(job, paper)} onAnswers={paper => onAnswers(job, paper)}
        />
      ))}</ul>}
    </div>
  )
}

// "Looks like a pair": answer papers matching found a likely question paper for, on evidence too
// weak to pair them unasked.
function Suggestions({ pairs, busy, onPair, onReject }) {
  if (!pairs.length) return null
  return (
    <section aria-label="Suggested pairs" className="mb-3 rounded border border-amber-200 bg-amber-50 px-4 py-3">
      <h2 className="text-sm font-semibold text-amber-900">Looks like a pair</h2>
      <ul className="mt-1.5 space-y-1.5">
        {pairs.map(s => (
          <li key={s.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-800">
            <span className="break-all"><b>{s.questions.filename}</b> + <b>{s.answers.filename}</b></span>
            {s.note && <span className="text-gray-500">({s.note})</span>}
            <span className="ml-auto flex gap-2">
              <button
                type="button" disabled={busy} onClick={() => onPair(s)} aria-label={`Pair ${s.answers.filename}`}
                className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-2.5 py-1 font-medium"
              >
                Pair
              </button>
              <button
                type="button" disabled={busy} onClick={() => onReject(s)} aria-label={`Not a pair: ${s.answers.filename}`}
                className="rounded border border-gray-300 bg-white px-2.5 py-1 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Not a pair
              </button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// Jobs the worker has finished, waiting for an admin to check and confirm them. Polled (through
// the import layout) so newly finished jobs appear on their own; the oldest waits at the top. A
// question booklet and the answer booklet linked to it share one card and one review.
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
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)

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

  const act = async call => {
    setBusy(true)
    setActionError(null)
    try {
      await call()
      refresh()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setBusy(false)
    }
  }
  const pair = s => act(() => api.import.matchJobPaper(s.answers.jobId, s.answers.key, s.questions.ingestPaperId))
  const reject = s => act(() => api.import.rejectSuggestion(s.answers.jobId, s.answers.key))
  const toAnswers = (job, paper) => {
    if (!window.confirm(`Treat ${job.filename} as an answer booklet? Its boxes become answer boxes, and it is matched to its question paper.`)) return
    act(() => api.import.switchPaperRole(job.id, paper.key, 'answer_only'))
  }

  const unmatched = j => (j.papers ?? []).some(p => p.role === 'answer_only' && p.status === 'pending' && !p.linked)
  const groups = groupJobs(jobs).filter(g => !unmatchedOnly || g.jobs.some(unmatched))

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
      <ErrorBanner message={error || actionError} />
      <Suggestions pairs={suggestedPairs(jobs)} busy={busy} onPair={pair} onReject={reject} />

      {groups.length === 0 ? (
        <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded px-3 py-4">
          {jobs.length === 0
            ? 'Nothing to review. Jobs appear here as soon as the worker finishes them — no need to refresh.'
            : 'No job has unmatched answers.'}
        </p>
      ) : (
        <ul aria-label="Jobs ready for review" className="space-y-2">
          {groups.map(group => (
            <li key={group.id} data-testid="review-card" className="bg-white border border-gray-200 rounded px-4 py-3 flex gap-4 items-start">
              <div className="flex-1 min-w-0 space-y-2">
                {group.pair && <p className="text-xs text-green-700">Questions and answers, reviewed together</p>}
                {group.jobs.map((job, i) => (
                  <div key={job.id} className={i > 0 ? 'border-t border-gray-100 pt-2' : ''}>
                    <JobBlock
                      job={job} role={group.pair ? jobRole(job) : null} isNew={fresh.has(job.id)} refs={refs} busy={busy}
                      onMatch={(j, paper) => setMatching({ jobId: j.id, paper })} onAnswers={toAnswers}
                    />
                  </div>
                ))}
              </div>
              <Link
                to={group.pair ? reviewUrl(group.pair.jobId, group.pair.key) : reviewUrl(group.jobs[0].id)}
                className="shrink-0 bg-blue-600 hover:bg-blue-700 text-white rounded px-3 py-1.5 text-sm font-medium"
              >
                Review
              </Link>
            </li>
          ))}
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
