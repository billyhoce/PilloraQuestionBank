import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { clientToPt, firstPageOf, rectToPx } from './reviewGeometry'
import {
  addRect, assignAnswer, deleteRect, getRect, mergeWithPrevious, moveRect, renumber, renumberError, resizeRect, splitBetween,
  splitThrough, toEditPayload,
} from './proposalReducer'
import { partlyAnsweredWarning } from './answerCoverage'
import { startManualImport } from './manualHandoff'
import MatchPanel from './MatchPanel'
import MetadataSidebar from './MetadataSidebar'
import TopicReview from './TopicReview'
import { emptyMetadata, mergeSuggested, useReferenceData } from './importMetadata'

// Proposals from before roles existed have no `role`: they are question papers.
const isAnswerOnly = paper => paper?.role === 'answer_only'

function paperTitle(paper, i) {
  return paper.label ? `${paper.label}${paper.answer_label ? ` / ${paper.answer_label}` : ''}` : `Answers ${paper.answer_label ?? i + 1}`
}

const SAVE_DELAY_MS = 800
const HANDLE_PX = 14
const COLOUR = { question: '#2563eb', answer: '#16a34a', orphan: '#6b7280' }

// Edge handles of the selected rectangle: which coordinate each one drags, and where it sits.
const HANDLES = [
  { edge: 'x0', cursor: 'ew-resize', at: b => ({ x: b.x - HANDLE_PX / 2, y: b.y, width: HANDLE_PX, height: b.height }) },
  { edge: 'x1', cursor: 'ew-resize', at: b => ({ x: b.x + b.width - HANDLE_PX / 2, y: b.y, width: HANDLE_PX, height: b.height }) },
  { edge: 'y0', cursor: 'ns-resize', at: b => ({ x: b.x, y: b.y - HANDLE_PX / 2, width: b.width, height: HANDLE_PX }) },
  { edge: 'y1', cursor: 'ns-resize', at: b => ({ x: b.x, y: b.y + b.height - HANDLE_PX / 2, width: b.width, height: HANDLE_PX }) },
]

const sameSel = (a, b) => a && b && a.list === b.list && a.i === b.i && (a.list === 'orphan' || a.q === b.q)

function Overlay({ page, paper, sel, onSelect, onResize, onMove, drawKind, onDraw }) {
  const svgRef = useRef(null)
  const drag = useRef(null)
  // The box being drawn, in points: { x0, y0, x1, y1 } (corners in drawing order).
  const [draft, setDraft] = useState(null)
  const boxes = []
  const add = (list, q, rects, label) =>
    rects.forEach((r, i) => {
      if (r.page === page.page) boxes.push({ list, q, i, label, box: rectToPx(r, page), rect: r })
    })
  paper.questions.forEach((q, k) => {
    add('question', k, q.question_rects, `Q${q.number}`)
    add('answer', k, q.answer_rects, `A${q.number}`)
  })
  add('orphan', null, paper.orphan_answers, null)

  const toPt = e => clientToPt(e.clientX, e.clientY, svgRef.current.getBoundingClientRect(), page)

  function move(e) {
    const d = drag.current
    if (!d) return
    const pt = toPt(e)
    if (d.edge) onResize(d.sel, { [d.edge]: d.edge[0] === 'x' ? pt.x : pt.y })
    else onMove(d.sel, d.rect.x0 + pt.x - d.start.x, d.rect.y0 + pt.y - d.start.y)
  }
  const endDrag = () => { drag.current = null }

  // Drawing: press on the page, drag, release.
  function drawStart(e) {
    if (!drawKind) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const pt = toPt(e)
    setDraft({ x0: pt.x, y0: pt.y, x1: pt.x, y1: pt.y })
  }
  function drawMove(e) {
    if (!draft) return
    const pt = toPt(e)
    setDraft(d => ({ ...d, x1: pt.x, y1: pt.y }))
  }
  function drawEnd() {
    if (!draft) return
    onDraw({ page: page.page, ...draft })
    setDraft(null)
  }

  const draftBox = draft && rectToPx({
    x0: Math.min(draft.x0, draft.x1), x1: Math.max(draft.x0, draft.x1),
    y0: Math.min(draft.y0, draft.y1), y1: Math.max(draft.y0, draft.y1),
  }, page)

  return (
    <svg
      ref={svgRef}
      data-testid="overlay"
      data-drawing={drawKind || undefined}
      viewBox={`0 0 ${page.width_px} ${page.height_px}`}
      className="absolute inset-0 w-full h-full"
      style={{ cursor: drawKind ? 'crosshair' : undefined, touchAction: drawKind ? 'none' : undefined }}
      onClick={() => { if (!drawKind) onSelect(null) }}
      onPointerDown={drawStart}
      onPointerMove={drawMove}
      onPointerUp={drawEnd}
      onPointerCancel={() => setDraft(null)}
    >
      {boxes.map(b => {
        const s = { list: b.list, q: b.q, i: b.i }
        const on = sameSel(sel, s)
        const inQuestion = sel && sel.list !== 'orphan' && b.q === sel.q
        return (
          <g key={`${b.list}-${b.q}-${b.i}`} data-kind={b.list} data-selected={on || undefined}
            pointerEvents={drawKind ? 'none' : undefined}>
            <rect
              {...b.box}
              data-testid={on ? 'selected-rect' : undefined}
              fill={COLOUR[b.list]}
              fillOpacity={on ? 0.3 : inQuestion ? 0.2 : 0.1}
              stroke={COLOUR[b.list]}
              strokeWidth={on || inQuestion ? 4 : 2}
              strokeDasharray={b.list === 'orphan' ? '8 4' : undefined}
              style={{ cursor: on ? 'move' : 'pointer', touchAction: on ? 'none' : undefined }}
              onClick={e => { e.stopPropagation(); onSelect(s) }}
              onPointerDown={on ? e => {
                // Drag the selected box to move it.
                e.stopPropagation()
                e.currentTarget.setPointerCapture?.(e.pointerId)
                drag.current = { sel: s, rect: b.rect, start: toPt(e) }
              } : undefined}
              onPointerMove={on ? move : undefined}
              onPointerUp={on ? endDrag : undefined}
              onPointerCancel={on ? endDrag : undefined}
            />
            {b.label && (
              <text x={b.box.x + 6} y={b.box.y + 22} fontSize="20" fill={COLOUR[b.list]} pointerEvents="none">
                {b.label}
              </text>
            )}
            {on && HANDLES.map(h => (
              <rect
                key={h.edge}
                data-testid={`handle-${h.edge}`}
                {...h.at(b.box)}
                fill={COLOUR[b.list]}
                fillOpacity={0.6}
                style={{ cursor: h.cursor, touchAction: 'none' }}
                onClick={e => e.stopPropagation()}
                onPointerDown={e => {
                  e.stopPropagation()
                  e.currentTarget.setPointerCapture?.(e.pointerId)
                  drag.current = { sel: s, edge: h.edge }
                }}
                onPointerMove={move}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              />
            ))}
          </g>
        )
      })}
      {draftBox && (
        <rect data-testid="draft-rect" {...draftBox} fill={COLOUR[drawKind]} fillOpacity={0.15}
          stroke={COLOUR[drawKind]} strokeWidth={2} strokeDasharray="6 3" pointerEvents="none" />
      )}
    </svg>
  )
}

// What the selected box is, in words, and what can be done to it: delete it, and for an answer
// box, give it to another question (or leave it unmatched).
function SelectionPanel({ paper, sel, onDelete, onAssign }) {
  const rect = getRect(paper, sel)
  if (!rect) return null
  const q = sel.list === 'orphan' ? null : paper.questions[sel.q]
  const what = sel.list === 'orphan' ? 'Unmatched answer box'
    : sel.list === 'answer' ? `Answer box of question ${q.number}`
      : `Question box of question ${q.number}`
  const canAssign = sel.list !== 'question' && paper.questions.length > 0
  return (
    <div role="region" aria-label="Selected box" className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1.5">
      <span className="font-medium text-gray-700">{what}</span>
      <span className="text-gray-500">page {rect.page} · drag to move, drag an edge to resize</span>
      {canAssign && (
        <label className="flex items-center gap-1 text-gray-700">
          Belongs to
          <select
            aria-label="Assign answer box to question"
            value={sel.list === 'orphan' ? '' : String(sel.q)}
            onChange={e => onAssign(e.target.value === '' ? null : Number(e.target.value))}
            className="border border-gray-300 rounded px-1 py-0.5 text-xs"
          >
            <option value="">No question (not imported)</option>
            {paper.questions.map((o, k) => <option key={k} value={k}>Question {o.number}</option>)}
          </select>
        </label>
      )}
      <button type="button" onClick={onDelete} className="ml-auto text-red-600 hover:underline">Delete box</button>
    </div>
  )
}

// The drawing tools: one press draws one box. Where it goes is said up front.
function DrawToolbar({ answerOnly, drawKind, onDrawKind, target }) {
  const tools = answerOnly ? [['answer', 'Draw answer box']] : [['question', 'Draw question box'], ['answer', 'Draw answer box']]
  const where = drawKind === 'question'
    ? (target != null ? `It is added to question ${target}.` : 'It becomes a new question.')
    : drawKind === 'answer'
      ? (target != null ? `It is added to the answers of question ${target}.` : answerOnly ? 'It becomes a new answer.' : 'It is left unmatched; assign it to a question afterwards.')
      : null
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
      {tools.map(([kind, label]) => (
        <button
          key={kind}
          type="button"
          aria-pressed={drawKind === kind}
          onClick={() => onDrawKind(drawKind === kind ? null : kind)}
          className={`rounded border px-2 py-1 font-medium ${
            drawKind === kind ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
          }`}
        >
          {label}
        </button>
      ))}
      {drawKind ? (
        <span role="status" className="text-gray-600">Drag on the page to draw. {where} Esc cancels.</span>
      ) : (
        <span className="text-gray-500">Click a box to select it; select a question first to add boxes to it.</span>
      )}
    </div>
  )
}

// A question's number; committed on blur or Enter, refused (with the reason) if it clashes.
function NumberField({ paper, q, onCommit }) {
  const number = paper.questions[q].number
  const [text, setText] = useState(String(number))
  const [error, setError] = useState(null)
  useEffect(() => { setText(String(number)); setError(null) }, [number])
  function commit() {
    const n = Number(text)
    const err = text.trim() === '' ? 'A question number must be a positive whole number' : renumberError(paper, q, n)
    setError(err)
    if (!err) onCommit(n)
  }
  return (
    <span className="inline-flex flex-col">
      <input
        type="number"
        min="1"
        aria-label={`Number of question ${number}`}
        aria-invalid={error ? 'true' : undefined}
        value={text}
        onChange={e => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit() }}
        className="w-14 border border-gray-300 rounded px-1 text-sm"
      />
      {error && <span role="alert" className="text-xs text-red-600">{error}</span>}
    </span>
  )
}

const SAVE_LABEL = { saving: 'Saving…', saved: 'Saved', error: 'Not saved' }

export default function ReviewPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  // The review queue, when this page sits under the import layout: for "next job".
  const reviewQueue = useOutletContext()?.reviewQueue
  const nextJob = (reviewQueue?.jobs ?? [])
    .filter(j => j.id !== jobId)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at))[0] ?? null
  // Drawing a new box: null, 'question' or 'answer' (one box per press of the tool).
  const [drawKind, setDrawKind] = useState(null)
  const [review, setReview] = useState(null)
  const [error, setError] = useState(null)
  const [paperIdx, setPaperIdx] = useState(0)
  const [pageNo, setPageNo] = useState(null)
  const [sel, setSel] = useState(null)
  const [saveState, setSaveState] = useState('idle')
  const timer = useRef(null)
  const latest = useRef(null)
  const [handoff, setHandoff] = useState(null)
  const refs = useReferenceData()
  // The admin's edits to the sidebar, by paper key; a paper never edited shows its own pre-fill.
  const [metadataEdits, setMetadataEdits] = useState({})
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState(null)
  // After a confirm: the created paper's questions, awaiting the topic-review step.
  const [topicStep, setTopicStep] = useState(null)
  // Papers linked to a paper of another job, by paper key: { filename, paper_key, ... }.
  const [matches, setMatches] = useState({})
  // Automatic matches of answer-only papers to confirmed papers, by key: { status, note, paper }.
  const [proposals, setProposals] = useState({})

  useEffect(() => {
    let live = true
    api.import.review(jobId)
      .then(r => {
        if (!live) return
        setReview(r)
        setMatches(r.matches ?? {})
        setProposals(r.proposals ?? {})
        // Open on the first paper still undecided.
        const first = r.proposal.papers.findIndex(p => !p.outcome)
        if (first > 0) setPaperIdx(first)
      })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobId])

  latest.current = review

  // The sidebar's edits are mirrored to the server (debounced, one timer per paper) so the paper's
  // ingest_paper row stays current. Best effort: confirm sends the final metadata regardless.
  const metaTimers = useRef({})
  const queueMetadataSave = (key, m) => {
    if (!key) return
    clearTimeout(metaTimers.current[key])
    metaTimers.current[key] = setTimeout(() => {
      delete metaTimers.current[key]
      api.import.savePaperMetadata(jobId, key, {
        subject_id: m.subject_id, stream_id: m.stream_id, level_id: m.level_id,
        school_id: m.school_id, exam_type_id: m.exam_type_id,
        ...(m.new_school_name && { new_school_name: m.new_school_name }),
        year: m.year === '' || m.year == null ? null : Number(m.year),
        paper_number: m.paper_number === '' ? null : m.paper_number,
      }).catch(() => {})
    }, 800)
  }
  const dropMetadataSave = key => {
    clearTimeout(metaTimers.current[key])
    delete metaTimers.current[key]
  }
  useEffect(() => () => Object.values(metaTimers.current).forEach(clearTimeout), [])

  const flush = useCallback(async () => {
    clearTimeout(timer.current)
    timer.current = null
    setSaveState('saving')
    try {
      await api.import.saveProposal(jobId, toEditPayload(latest.current.proposal.papers))
      // A newer edit may have been queued while this one was in flight; it keeps "saving".
      if (!timer.current) setSaveState('saved')
      setError(null)
    } catch (e) {
      setSaveState('error')
      setError(e.message)
    }
  }, [jobId])

  // Leaving the page with an edit still waiting for its debounce saves it now.
  useEffect(() => () => { if (timer.current) flush() }, [flush])

  const papers = review?.proposal.papers ?? []
  const paper = papers[paperIdx]
  // Pre-filled from the paper's own cover; an old job has only the filename's guess for the booklet.
  const metadata = metadataEdits[paper?.key]
    ?? mergeSuggested(emptyMetadata, review?.paper_metadata?.[paper?.key] ?? review?.filename_metadata ?? {})
  const setMetadata = m => {
    const key = paper?.key
    setMetadataEdits(e => ({ ...e, [key]: m }))
    queueMetadataSave(key, m)
  }
  const answerOnly = isAnswerOnly(paper)
  // Answers are all or none: a question paper that would be confirmed partly answered (its own
  // answer boxes plus a linked answer paper's, by number) is warned about, never blocked.
  const unansweredText = paper && !answerOnly ? partlyAnsweredWarning(paper, matches[paper.key]?.answer_numbers ?? []) : null
  const page = paper ? (paper.pages.find(p => p.page === pageNo) ?? paper.pages[0]) : null

  function choosePaper(i) {
    setPaperIdx(i)
    setPageNo(null)
    setSel(null)
    setDrawKind(null)
  }

  function chooseQuestion(k) {
    setSel({ list: isAnswerOnly(paper) ? 'answer' : 'question', q: k, i: 0 })
    const p = firstPageOf(paper.questions[k])
    if (p != null) setPageNo(p)
  }

  // Apply a pure edit to the current paper and queue a debounced save. `nextSel` is the
  // selection afterwards (default: cleared, since indexes may have shifted).
  function edit(fn, nextSel = null) {
    const next = fn(paper)
    if (next === paper) return
    setReview(r => ({
      ...r,
      edited: true,
      proposal: { ...r.proposal, papers: r.proposal.papers.map((p, i) => (i === paperIdx ? next : p)) },
    }))
    setSel(nextSel)
    setSaveState('saving')
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, SAVE_DELAY_MS)
  }

  const onResize = (s, edges) => edit(p => resizeRect(p, s, edges), s)
  const onMove = (s, x0, y0) => edit(p => moveRect(p, s, x0, y0), s)

  // A drawn box goes to the selected question if there is one, else starts a new question (or,
  // for an answer box in a question paper, an unmatched answer). The new box is selected.
  function onDraw(drawn) {
    const q = sel && sel.list !== 'orphan' ? sel.q : null
    const { paper: next, sel: nextSel } = addRect(paper, drawKind, q, drawn)
    setDrawKind(null)
    if (next !== paper) edit(() => next, nextSel)
  }

  function onAssign(toQ) {
    const { paper: next, sel: nextSel } = assignAnswer(paper, sel, toQ)
    if (next !== paper) edit(() => next, nextSel)
  }

  useEffect(() => {
    function onKey(e) {
      const t = e.target
      if (t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable)) return
      if (e.key === 'Escape') {
        if (drawKind) setDrawKind(null)
        else setSel(null)
        return
      }
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      if (!sel) return
      e.preventDefault()
      edit(p => deleteRect(p, sel))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // Mark the current paper decided; carry on with the next undecided one, or leave when none is.
  function decided(outcome, jobStatus) {
    setReview(r => ({
      ...r,
      proposal: { ...r.proposal, papers: r.proposal.papers.map((p, i) => (i === paperIdx ? { ...p, outcome } : p)) },
    }))
    setTopicStep(null)
    if (jobStatus === 'confirmed') {
      reviewQueue?.refresh()
      navigate(nextJob ? `/admin/import/jobs/${nextJob.id}/review` : '/admin/import/review')
      return
    }
    const next = papers.findIndex((p, i) => i !== paperIdx && !p.outcome)
    if (next >= 0) choosePaper(next)
  }

  async function handleConfirmPaper() {
    dropMetadataSave(paper.key)  // confirm carries the final metadata itself
    setConfirming(true)
    setConfirmError(null)
    try {
      // The server crops the saved proposal, so a pending edit goes first.
      if (timer.current) await flush()
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

  // After Unmatch or "Not this one": what matching found for the paper instead.
  function rematched(key, { matches: link, proposal }) {
    setMatches(m => ({ ...m, [key]: link ?? null }))
    setProposals(p => ({ ...p, [key]: proposal ?? null }))
  }

  async function unmatchPaper() {
    const key = paper.key
    try {
      rematched(key, await api.import.unmatchJobPaper(jobId, key))
    } catch (e) {
      setConfirmError(e.message)
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

  async function handleManually(item) {
    setHandoff(item.label)
    setError(null)
    try {
      const result = await api.import.manualPages(jobId, item.first_page, item.last_page)
      startManualImport(result)
      navigate('/admin/import/manual')
    } catch (e) {
      setError(e.message)
      setHandoff(null)
    }
  }

  if (error && !review) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-6">
        <ErrorBanner message={error} />
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
                Attached answers for question{answersFrom.attached.length === 1 ? '' : 's'} {answersFrom.attached.join(', ')} from {answersFrom.filename} ({answersFrom.paper_key}).
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
  const flaggedPage = p => p.needs_review

  return (
    <div className="px-4 py-4">
      <div className="flex items-center gap-4 mb-3">
        <Link to="/admin/import/review" className="text-sm text-blue-600 hover:underline">← Review queue</Link>
        <h1 className="text-lg font-semibold text-gray-800 break-all">{review.filename}</h1>
        {review.edited && <span className="text-xs text-gray-500">edited</span>}
        {saveState !== 'idle' && (
          <span role="status" data-state={saveState} className={`text-xs ${saveState === 'error' ? 'text-red-600' : 'text-gray-500'}`}>
            {SAVE_LABEL[saveState]}
          </span>
        )}
        {nextJob && (
          <Link to={`/admin/import/jobs/${nextJob.id}/review`} className="ml-auto text-sm text-blue-600 hover:underline">
            Next job: <span className="break-all">{nextJob.filename}</span> →
          </Link>
        )}
      </div>
      <ErrorBanner message={error} />

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

      {!paper ? (
        <p className="text-sm text-gray-500">No paper was proposed for this job.</p>
      ) : (
        <div className="flex gap-4 items-start">
          <nav aria-label="Pages" className="w-24 shrink-0 space-y-2 max-h-[80vh] overflow-y-auto">
            {paper.pages.map(p => (
              <button
                key={p.page}
                type="button"
                data-flagged={flaggedPage(p) || undefined}
                aria-current={page && p.page === page.page ? 'page' : undefined}
                title={p.review_reason || undefined}
                onClick={() => setPageNo(p.page)}
                className={`block w-full border-2 rounded text-xs ${
                  page && p.page === page.page ? 'border-blue-600' : flaggedPage(p) ? 'border-amber-400' : 'border-gray-200'
                }`}
              >
                {p.url && <img src={p.url} alt={`Page ${p.page} thumbnail`} className="w-full" />}
                <span className="block py-0.5">p{p.page}{flaggedPage(p) ? ' !' : ''}</span>
              </button>
            ))}
          </nav>

          <div className="flex-1 min-w-0">
            {page ? (
              <>
                {!paper.outcome && (
                  <DrawToolbar
                    answerOnly={answerOnly}
                    drawKind={drawKind}
                    onDrawKind={setDrawKind}
                    target={sel && sel.list !== 'orphan' ? paper.questions[sel.q]?.number : null}
                  />
                )}
                {!paper.outcome && sel && !drawKind && (
                  <SelectionPanel paper={paper} sel={sel} onDelete={() => edit(p => deleteRect(p, sel))} onAssign={onAssign} />
                )}
                {flaggedPage(page) && (
                  <p className="mb-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-1">
                    Page {page.page} needs review{page.review_reason ? `: ${page.review_reason}` : ''}
                  </p>
                )}
                <div
                  className="relative mx-auto max-w-3xl border border-gray-300"
                  style={{ aspectRatio: `${page.width_px} / ${page.height_px}` }}
                >
                  {page.url ? (
                    <img src={page.url} alt={`Page ${page.page}`} className="absolute inset-0 w-full h-full" />
                  ) : (
                    <p className="p-4 text-sm text-gray-500">The image for this page is missing.</p>
                  )}
                  <Overlay
                    page={page} paper={paper} sel={sel} onSelect={setSel} onResize={onResize} onMove={onMove}
                    drawKind={paper.outcome ? null : drawKind} onDraw={onDraw}
                  />
                </div>
              </>
            ) : (
              <p className="text-sm text-gray-500">This paper has no pages.</p>
            )}
          </div>

          <aside aria-label="Questions" className="w-64 shrink-0 max-h-[80vh] overflow-y-auto">
            {paper.warnings?.map((w, i) => (
              <p key={i} className="mb-2 text-xs text-amber-800">{w}</p>
            ))}
            {paper.questions.length === 0 ? (
              <p className="text-sm text-gray-500">No questions were found for this paper.</p>
            ) : (
              <ul className="space-y-1">
                {paper.questions.map((q, k) => {
                  const active = sel != null && sel.list !== 'orphan' && sel.q === k
                  const onQuestionRect = active && sel.list === 'question'
                  const rect = onQuestionRect ? getRect(paper, sel) : null
                  return (
                    <li key={k} className={`rounded border px-2 py-1 ${
                      active ? 'border-blue-600 bg-blue-50' : q.flags.length ? 'border-amber-300 bg-amber-50' : 'border-gray-200'
                    }`}>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          data-flagged={q.flags.length > 0 || undefined}
                          aria-pressed={active}
                          onClick={() => chooseQuestion(k)}
                          className="flex-1 text-left text-sm"
                        >
                          <span className="font-medium">{answerOnly ? 'Answer' : 'Question'} {q.number}</span>
                          {answerOnly && (
                            <span className="text-xs text-gray-500">
                              {' '}({q.answer_rects.length} rectangle{q.answer_rects.length === 1 ? '' : 's'})
                            </span>
                          )}
                          {!answerOnly && q.answer_rects.length === 0 && <span className="text-xs text-gray-500"> (no answer)</span>}
                          {q.flags.map(f => (
                            <span key={f} className="block text-xs text-amber-800">{f}</span>
                          ))}
                        </button>
                        <NumberField paper={paper} q={k} onCommit={n => edit(p => renumber(p, k, n), sel)} />
                      </div>
                      {active && (
                        <div className="mt-1 flex flex-wrap gap-1 text-xs">
                          {k > 0 && (
                            <button type="button" className="text-blue-700 hover:underline"
                              onClick={() => edit(p => mergeWithPrevious(p, k))}>
                              Merge with previous
                            </button>
                          )}
                          {rect && sel.i > 0 && (
                            <button type="button" className="text-blue-700 hover:underline"
                              onClick={() => edit(p => splitBetween(p, k, sel.i))}>
                              Split before selected rectangle
                            </button>
                          )}
                          {rect && (
                            <button type="button" className="text-blue-700 hover:underline"
                              onClick={() => edit(p => splitThrough(p, k, sel.i, (rect.y0 + rect.y1) / 2))}>
                              Split selected rectangle in half
                            </button>
                          )}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
            {paper.orphan_answers.length > 0 && (
              <p className="mt-2 text-xs text-gray-600">
                {paper.orphan_answers.length} answer rectangle{paper.orphan_answers.length === 1 ? '' : 's'} not matched to a question (grey, dashed).
                They are not imported.
              </p>
            )}
          </aside>

          {paper.outcome ? (
            <p role="status" className="w-52 shrink-0 text-sm text-gray-600">This paper was {paper.outcome}.</p>
          ) : (
            <div className="shrink-0">
              {answerOnly && (
                <p className="w-52 mb-2 text-xs text-gray-600">
                  These are answers only, with no question paper in this booklet. Attach them to the paper they belong to.
                </p>
              )}
              {paper.questions.length === 0 && (
                <p className="w-52 mb-2 text-xs text-amber-800">
                  A paper without questions cannot be imported; skip it.
                </p>
              )}
              {!answerOnly && matches[paper.key] && (
                <p role="status" className="w-52 mb-2 text-xs bg-blue-50 border border-blue-200 rounded px-2 py-1.5">
                  Answers available from {matches[paper.key].filename} ({matches[paper.key].paper_key}) — they will be attached when you confirm.{' '}
                  <button type="button" onClick={unmatchPaper} className="text-blue-700 hover:underline">Unmatch</button>
                </p>
              )}
              {answerOnly ? (
                <MatchPanel
                  key={paper.key}
                  jobId={jobId}
                  paper={paper}
                  metadata={metadata}
                  refs={refs}
                  link={matches[paper.key] ?? null}
                  proposal={proposals[paper.key] ?? null}
                  onLink={link => setMatches(m => ({ ...m, [paper.key]: link }))}
                  onRematched={r => rematched(paper.key, r)}
                  onFlush={async () => { if (timer.current) await flush() }}
                  onAttached={jobStatus => decided('attached', jobStatus)}
                  onSkip={handleSkipPaper}
                  busy={confirming}
                />
              ) : (
                <MetadataSidebar
                  metadata={metadata}
                  onChange={setMetadata}
                  refs={refs}
                  questionCount={paper.questions.length}
                  answerCount={paper.questions.filter(q => q.answer_rects.length > 0).length}
                  onNext={handleConfirmPaper}
                  onCancel={handleSkipPaper}
                  loading={confirming}
                  error={confirmError}
                  confirmLabel="Confirm paper →"
                  cancelLabel="Skip this paper"
                  canConfirm={paper.questions.length > 0}
                  schoolCombobox
                  extractedSchool={review.paper_metadata?.[paper.key]?.extracted?.school ?? null}
                  warning={unansweredText && `${unansweredText}. Add them with the answer-box editor, or confirm anyway.`}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
