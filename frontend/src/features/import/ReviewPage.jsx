import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useOutletContext, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { partlyAnsweredWarning } from './answerCoverage'
import { answersOn, startMapping } from './answerMapping'
import { startManualImport } from './manualHandoff'
import MetadataSidebar from './MetadataSidebar'
import PairingBlock from './PairingBlock'
import { isAnswerOnly, metadataBody, needsPartner, pairingState } from './pairing'
import PaperEditor from './PaperEditor'
import { groupJobs } from './queueGroups'
import RectPreview from './RectPreview'
import TopicReview from './TopicReview'
import { emptyMetadata, mergeSuggested, useReferenceData } from './importMetadata'
import useJobReview from './useJobReview'

function paperTitle(paper, i) {
  return paper.label ? `${paper.label}${paper.answer_label ? ` / ${paper.answer_label}` : ''}` : `Answers ${paper.answer_label ?? i + 1}`
}

// A linked partner's file: "this file" when it is in the same booklet (#90).
const fileName = (link, jobId) => (link.job_id === jobId ? 'this file' : link.filename)

const reviewUrl = (jobId, key) => `/admin/import/jobs/${jobId}/review${key ? `?paper=${encodeURIComponent(key)}` : ''}`

const SAVE_LABEL = { saving: 'Saving…', saved: 'Saved', error: 'Not saved' }
// Two jobs saving at once (a paired review) show the state that most needs attention.
const worstSave = (...states) => ['error', 'saving', 'saved'].find(s => states.includes(s)) ?? 'idle'

// The linked answer paper's answers, placed onto question paper `paper`'s questions by the pair's
// stored mapping, else by number: { [question label]: [{ label, k, answer }] } (`k`, the answer's
// index in the answer paper).
function placedAnswers(paper, answersPaper, mapping) {
  const answers = answersPaper.questions
    .map((a, k) => ({ label: String(a.number), k, answer: a }))
    .filter(a => a.answer.answer_rects.length > 0)
  const questions = paper.questions.map(q => ({ label: String(q.number) }))
  const placed = startMapping(questions, answers, mapping)
  return Object.fromEntries(questions.map(q => [q.label, answersOn(placed, answers, q.label)]))
}

// Under a question in a paired review: the answers landing on it from the answer booklet, each a
// thumbnail that opens that answer's box, or "No answer".
function LinkedAnswers({ placed, answersPaper, onOpen }) {
  if (!placed.length) return <p className="text-xs text-amber-800">No answer</p>
  return (
    <ul className="mt-1 flex flex-wrap gap-1">
      {placed.map(({ label, k, answer }) => {
        const rect = answer.answer_rects[0]
        const page = answersPaper.pages.find(p => p.page === rect.page)
        return (
          <li key={label}>
            <button
              type="button" onClick={() => onOpen(k, rect.page)} aria-label={`Open answer ${label}`}
              title={`Answer ${label}, page ${rect.page}: open it in the answer booklet`}
              className="block w-20 text-left text-[10px] text-green-800 hover:ring-2 hover:ring-green-500 rounded"
            >
              {page?.url ? <RectPreview url={page.url} page={page} rect={rect} alt={`Answer ${label}`} /> : null}
              <span>A{label} · p{rect.page}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

export default function ReviewPage() {
  const { jobId } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  // The review queue, when this page sits under the import layout: for "next job".
  const reviewQueue = useOutletContext()?.reviewQueue
  const main = useJobReview(jobId)
  const { review, matches, proposals } = main
  // The paper the admin opened, { jobId, idx }; until then the one the page opens on.
  const [chosen, setChosen] = useState(null)
  const [handoff, setHandoff] = useState(null)
  const refs = useReferenceData()
  // The admin's edits to the sidebar, by paper key; a paper never edited shows its own pre-fill.
  const [metadataEdits, setMetadataEdits] = useState({})
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState(null)
  // After a confirm: the created paper's questions, awaiting the topic-review step.
  const [topicStep, setTopicStep] = useState(null)
  // A paired review: which booklet the editor shows and where it opens ({ at, view, focus }, `at`
  // naming the paper it was chosen on; any other paper opens on its questions).
  const [shown, setShown] = useState(null)

  const papers = review?.proposal.papers ?? []
  // Open on the paper the link names (?paper=q1), else the first undecided one.
  const asked = papers.findIndex(p => p.key === search.get('paper'))
  const paperIdx = chosen?.jobId === jobId ? chosen.idx : asked >= 0 ? asked : Math.max(papers.findIndex(p => !p.outcome), 0)
  const paper = papers[paperIdx]
  const answerOnly = isAnswerOnly(paper)
  const link = paper ? matches[paper.key] ?? null : null

  // A question paper linked to an answer-only paper is reviewed with it: its booklet, in another
  // job or this one, is loaded alongside.
  const paired = paper && !answerOnly && !paper.outcome && link ? link : null
  const otherJob = paired && paired.job_id !== jobId ? paired.job_id : null
  const partner = useJobReview(otherJob)
  const partnerJob = otherJob ? partner : main
  const answersIdx = paired ? (partnerJob.review?.proposal.papers.findIndex(p => p.key === paired.paper_key) ?? -1) : -1
  const answersPaper = answersIdx >= 0 ? partnerJob.review.proposal.papers[answersIdx] : null
  const placed = answersPaper ? placedAnswers(paper, answersPaper, paired.answer_map) : null

  const at = `${jobId}:${paper?.key}`
  const view = shown?.at === at ? shown.view : 'questions'
  const focus = shown?.at === at ? shown.focus : null
  const setView = v => setShown({ at, view: v, focus: null })

  // An answer booklet whose every undecided paper is reviewed with its question paper in another
  // job opens there instead.
  useEffect(() => {
    if (!review) return
    const open = review.proposal.papers.filter(p => !p.outcome)
    const elsewhere = open.map(p => matches[p.key]).filter(l => l && l.job_id !== jobId && l.job_status === 'review_ready')
    if (open.length && elsewhere.length === open.length && open.every(isAnswerOnly)) {
      navigate(reviewUrl(elsewhere[0].job_id, elsewhere[0].paper_key), { replace: true })
    }
  }, [review, matches, jobId, navigate])

  // "Next job": the oldest card of the queue other than this one (a pair counts as one).
  const here = new Set([jobId, otherJob].filter(Boolean))
  const nextGroup = groupJobs(reviewQueue?.jobs ?? []).find(g => !g.jobs.some(j => here.has(j.id))) ?? null
  const nextUrl = nextGroup && (nextGroup.pair ? reviewUrl(nextGroup.pair.jobId, nextGroup.pair.key) : reviewUrl(nextGroup.jobs[0].id))

  // The sidebar's edits are mirrored to the server (debounced, one timer per paper) so the paper's
  // ingest_paper row stays current. Best effort: confirm sends the final metadata regardless.
  const metaTimers = useRef({})
  const queueMetadataSave = (key, m) => {
    if (!key) return
    clearTimeout(metaTimers.current[key])
    metaTimers.current[key] = setTimeout(() => {
      delete metaTimers.current[key]
      api.import.savePaperMetadata(jobId, key, metadataBody(m)).catch(() => {})
    }, 800)
  }
  const dropMetadataSave = key => {
    clearTimeout(metaTimers.current[key])
    delete metaTimers.current[key]
  }
  useEffect(() => () => Object.values(metaTimers.current).forEach(clearTimeout), [])

  // Pre-filled from the paper's own cover; an old job has only the filename's guess for the booklet.
  const metadata = metadataEdits[paper?.key]
    ?? mergeSuggested(emptyMetadata, review?.paper_metadata?.[paper?.key] ?? review?.filename_metadata ?? {})
  const setMetadata = m => {
    const key = paper?.key
    setMetadataEdits(e => ({ ...e, [key]: m }))
    queueMetadataSave(key, m)
  }
  // Answers are all or none: a question paper that would be confirmed partly answered (its own
  // answer boxes plus a linked answer paper's, as the pair's mapping places them) is warned
  // about, never blocked. A paired review counts the answer booklet's boxes as they stand.
  const linkedNumbers = placed
    ? paper.questions.filter(q => placed[String(q.number)].length).map(q => q.number)
    : link?.answer_numbers ?? []
  const unansweredText = paper && !answerOnly ? partlyAnsweredWarning(paper, linkedNumbers) : null

  // Both booklets' waiting edits are saved before anything the server crops.
  const saveAll = async () => {
    await main.flushPending()
    if (otherJob) await partner.flushPending()
  }

  function choosePaper(i) {
    setChosen({ jobId, idx: i })
  }

  // Mark the current paper decided; carry on with the next undecided one, or leave when none is.
  function decided(outcome, jobStatus) {
    main.markDecided(paper.key, outcome)
    setTopicStep(null)
    if (jobStatus === 'confirmed') {
      reviewQueue?.refresh()
      navigate(nextUrl ?? '/admin/import/review')
      return
    }
    const next = papers.findIndex((p, i) => i !== paperIdx && !p.outcome)
    choosePaper(next >= 0 ? next : paperIdx)
  }

  async function handleConfirmPaper() {
    dropMetadataSave(paper.key)  // confirm carries the final metadata itself
    setConfirming(true)
    setConfirmError(null)
    try {
      // The server crops the saved proposals, so pending edits go first.
      await saveAll()
      const result = await api.import.confirmJobPaper(jobId, {
        paper_label: paper.key,
        subject_id: metadata.subject_id,
        stream_id: metadata.stream_id,
        level_id: metadata.level_id,
        school_id: metadata.school_id,
        ...(metadata.new_school_name && { new_school_name: metadata.new_school_name }),  // created on confirm
        exam_type_id: metadata.exam_type_id,
        year: Number(metadata.year),
        paper_number: metadata.paper_number,
        is_premium: metadata.is_premium,
      })
      setTopicStep({
        paperId: result.paper_id, questions: result.questions || [], jobStatus: result.job_status,
        answersFrom: result.answers_from ?? null, unmatched: result.unmatched ?? [],
      })
    } catch (e) {
      setConfirmError(e.message)
    } finally {
      setConfirming(false)
    }
  }

  // After a pair, Unmatch or "Not this one": what the paper has now. A pair that also updated the
  // paper's details (saved by the match route) shows them in the sidebar, without saving again.
  function matched(key, { matches: newLink, proposal }, fields = null) {
    main.setMatches(m => ({ ...m, [key]: newLink ?? null }))
    main.setProposals(p => ({ ...p, [key]: proposal ?? null }))
    if (fields) {
      dropMetadataSave(key)
      setMetadataEdits(e => ({ ...e, [key]: { ...metadata, ...fields } }))
    }
  }

  async function handleSkipPaper() {
    if (!window.confirm(`Skip ${paperTitle(paper, paperIdx)}? It will not be imported.`)) return
    dropMetadataSave(paper.key)
    setConfirming(true)
    setConfirmError(null)
    try {
      const result = await api.import.skipJobPaper(jobId, paper.key)
      decided('skipped', result.job_status)
    } catch (e) {
      setConfirmError(e.message)
    } finally {
      setConfirming(false)
    }
  }

  // "This is an answer booklet" / "This is a question booklet": the paper's boxes change sides and
  // it is matched afresh, so the review is loaded again.
  async function handleSwitchRole(role) {
    const what = role === 'answer_only' ? 'an answer booklet: its boxes become answer boxes' : 'a question booklet: its answer boxes become question boxes'
    if (!window.confirm(`Treat ${paperTitle(paper, paperIdx)} as ${what}, and match it again?`)) return
    setConfirming(true)
    setConfirmError(null)
    try {
      await saveAll()
      await api.import.switchPaperRole(jobId, paper.key, role)
      reviewQueue?.refresh()
      main.reload()
    } catch (e) {
      setConfirmError(e.message)
    } finally {
      setConfirming(false)
    }
  }

  async function handleManually(item) {
    setHandoff(item.label)
    main.setError(null)
    try {
      const result = await api.import.manualPages(jobId, item.first_page, item.last_page)
      startManualImport(result)
      navigate('/admin/import/manual')
    } catch (e) {
      main.setError(e.message)
      setHandoff(null)
    }
  }

  if (main.error && !review) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-6">
        <ErrorBanner message={main.error} />
        <Link to="/admin/import/review" className="text-blue-600 hover:underline text-sm">Back to review queue</Link>
      </div>
    )
  }
  if (!review) return <Spinner />

  if (topicStep) {
    const { answersFrom, unmatched } = topicStep
    return (
      <>
        {(answersFrom || unmatched.length > 0) && (
          <div role="status" className="mx-4 mt-4 text-sm bg-blue-50 border border-blue-200 rounded px-3 py-2">
            {answersFrom && (
              <p>
                Attached answers for question{answersFrom.attached.length === 1 ? '' : 's'} {answersFrom.attached.join(', ')} from {fileName(answersFrom, jobId)} ({answersFrom.paper_key}).
              </p>
            )}
            {unmatched.length > 0 && (
              <p className="text-amber-800">
                Answers for {unmatched.length === 1 ? 'question' : 'questions'} {unmatched.join(', ')} matched no question and were not attached.
              </p>
            )}
          </div>
        )}
        <TopicReview
          paperId={topicStep.paperId}
          questions={topicStep.questions}
          subjectId={metadata.subject_id}
          streamId={metadata.stream_id}
          onDone={() => decided('confirmed', topicStep.jobStatus)}
          onCancel={() => decided('confirmed', topicStep.jobStatus)}
          cancelLabel="Skip topics (set them later in Manage Papers)"
        />
      </>
    )
  }

  const unrouted = review.proposal.unrouted ?? []
  const saveState = worstSave(main.saveState, otherJob ? partner.saveState : 'idle')
  const showingAnswers = view === 'answers' && answersPaper
  const linkedElsewhere = answerOnly && link && link.job_id !== jobId && !paper.outcome

  const openAnswer = (k, pageNo) => {
    setShown({ at, view: 'answers', focus: { page: pageNo, sel: { list: 'answer', q: k, i: 0 }, token: Date.now() } })
  }

  const sidebar = paper && (paper.outcome ? (
    <p role="status" className="w-52 shrink-0 text-sm text-gray-600">This paper was {paper.outcome}.</p>
  ) : (
    <div className="shrink-0">
      {answerOnly && (
        <p className="w-52 mb-2 text-xs text-gray-600">
          These are answers only, with no question paper in this booklet. Pair them with the paper they belong to.
        </p>
      )}
      {paper.questions.length === 0 && (
        <p className="w-52 mb-2 text-xs text-amber-800">
          A paper without questions cannot be imported; skip it.
        </p>
      )}
      {(needsPartner(paper) || pairingState({ link, proposal: proposals[paper.key] }) !== 'none') && (
        <PairingBlock
          key={paper.key}
          jobId={jobId}
          paper={paper}
          link={link}
          proposal={proposals[paper.key] ?? null}
          metadata={metadata}
          extractedSchool={review.paper_metadata?.[paper.key]?.extracted?.school ?? null}
          refs={refs}
          busy={confirming}
          beforeSave={saveAll}  // the server crops the saved proposals
          onMatched={(state, fields) => matched(paper.key, state, fields)}
          onAttached={jobStatus => decided('attached', jobStatus)}
        />
      )}
      {!link && (answerOnly || needsPartner(paper)) && (
        <button
          type="button" disabled={confirming} onClick={() => handleSwitchRole(answerOnly ? 'question' : 'answer_only')}
          className="w-52 mb-3 text-xs text-gray-600 hover:text-gray-800 hover:underline text-left disabled:opacity-50"
        >
          {answerOnly ? 'This is a question booklet' : 'This is an answer booklet'}
        </button>
      )}
      {answerOnly ? (
        <div className="w-52 flex flex-col gap-2">
          {confirmError && <ErrorBanner message={confirmError} />}
          <button type="button" onClick={handleSkipPaper} disabled={confirming}
            className="text-xs text-red-600 hover:text-red-700 text-center disabled:opacity-50">
            Skip this paper
          </button>
        </div>
      ) : (
        <MetadataSidebar
          metadata={metadata}
          onChange={setMetadata}
          refs={refs}
          questionCount={paper.questions.length}
          answerCount={placed ? linkedNumbers.length : paper.questions.filter(q => q.answer_rects.length > 0).length}
          onNext={handleConfirmPaper}
          onCancel={handleSkipPaper}
          loading={confirming}
          error={confirmError}
          confirmLabel={paired ? 'Confirm paper and answers →' : 'Confirm paper →'}
          cancelLabel="Skip this paper"
          canConfirm={paper.questions.length > 0}
          schoolCombobox
          extractedSchool={review.paper_metadata?.[paper.key]?.extracted?.school ?? null}
          warning={unansweredText && `${unansweredText}. Add them with the answer-box editor, or confirm anyway.`}
        />
      )}
    </div>
  ))

  return (
    <div className="px-4 py-4">
      <div className="flex items-center gap-4 mb-3">
        <Link to="/admin/import/review" className="text-sm text-blue-600 hover:underline">← Review queue</Link>
        <h1 className="text-lg font-semibold text-gray-800 break-all">
          {review.filename}
          {otherJob && partner.review && <span className="font-normal text-gray-500"> + {partner.review.filename}</span>}
        </h1>
        {(review.edited || partner.review?.edited) && <span className="text-xs text-gray-500">edited</span>}
        {saveState !== 'idle' && (
          <span role="status" data-state={saveState} className={`text-xs ${saveState === 'error' ? 'text-red-600' : 'text-gray-500'}`}>
            {SAVE_LABEL[saveState]}
          </span>
        )}
        {nextGroup && (
          <Link to={nextUrl} className="ml-auto text-sm text-blue-600 hover:underline">
            Next job: <span className="break-all">{nextGroup.jobs[0].filename}</span> →
          </Link>
        )}
      </div>
      <ErrorBanner message={main.error || (otherJob ? partner.error : null)} />

      {unrouted.length > 0 && (
        <ul aria-label="Unrouted sections" className="mb-3 space-y-2">
          {unrouted.map(u => (
            <li key={u.label} className="text-sm bg-amber-50 border border-amber-200 rounded px-3 py-2">
              <span className="font-medium">Section {u.label} was not extracted</span>
              {u.first_page != null && <span> (pages {u.first_page}–{u.last_page})</span>}
              <span>: {u.reason}</span>
              {u.first_page != null && (
                <button
                  type="button"
                  disabled={handoff === u.label}
                  onClick={() => handleManually(u)}
                  className="ml-3 text-blue-700 hover:underline"
                >
                  Handle manually
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {papers.length > 1 && (
        <div role="tablist" aria-label="Papers" className="flex gap-1 mb-3 border-b border-gray-200">
          {papers.map((p, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={i === paperIdx}
              onClick={() => choosePaper(i)}
              className={`px-3 py-1.5 text-sm -mb-px border-b-2 ${i === paperIdx ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500'}`}
            >
              {paperTitle(p, i)}
              {p.outcome && <span className="ml-1 text-xs text-gray-500">({p.outcome})</span>}
            </button>
          ))}
        </div>
      )}

      {linkedElsewhere && (
        <p role="note" className="mb-3 text-sm bg-green-50 border border-green-200 rounded px-3 py-2">
          Reviewed together with {link.filename} ({link.paper_key}).{' '}
          <Link to={reviewUrl(link.job_id, link.paper_key)} className="text-blue-700 hover:underline">Open pair</Link>
        </p>
      )}

      {paired && (
        <div role="group" aria-label="Booklet" className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          {[['questions', 'Questions', review.filename], ['answers', 'Answers', fileName(paired, jobId)]].map(([v, label, file]) => (
            <button
              key={v} type="button" aria-pressed={view === v} disabled={v === 'answers' && !answersPaper}
              onClick={() => setView(v)}
              className={`rounded border px-3 py-1 ${view === v ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'} disabled:opacity-50`}
            >
              {label} · <span className="break-all">{file}</span>
            </button>
          ))}
          {!answersPaper && <span className="text-xs text-gray-500">Loading the answer booklet…</span>}
        </div>
      )}

      {!paper ? (
        <p className="text-sm text-gray-500">No paper was proposed for this job.</p>
      ) : showingAnswers ? (
        <PaperEditor
          key={`answers:${paired.job_id}:${paired.paper_key}:${focus?.token ?? ''}`}
          paper={answersPaper}
          onChange={next => partnerJob.setPaper(answersIdx, next)}
          focus={focus}
          aside={sidebar}
        />
      ) : (
        <PaperEditor
          key={`${jobId}:${paper.key}`}
          paper={paper}
          onChange={next => main.setPaper(paperIdx, next)}
          renderAnswers={placed ? q => (
            <LinkedAnswers placed={placed[String(q.number)]} answersPaper={answersPaper} onOpen={openAnswer} />
          ) : null}
          aside={sidebar}
        />
      )}
    </div>
  )
}
