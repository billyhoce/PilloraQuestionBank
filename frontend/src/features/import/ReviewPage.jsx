import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { clientToPt, firstPageOf, rectToPx } from './reviewGeometry'
import {
  deleteRect, getRect, mergeWithPrevious, renumber, renumberError, resizeRect, splitBetween, splitThrough, toEditPayload,
} from './proposalReducer'
import { startManualImport } from './manualHandoff'
import MetadataSidebar from './MetadataSidebar'
import TopicReview from './TopicReview'
import { emptyMetadata, mergeSuggested, useReferenceData } from './importMetadata'

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

function Overlay({ page, paper, sel, onSelect, onResize }) {
  const svgRef = useRef(null)
  const drag = useRef(null)
  const boxes = []
  const add = (list, q, rects, label) =>
    rects.forEach((r, i) => {
      if (r.page === page.page) boxes.push({ list, q, i, label, box: rectToPx(r, page) })
    })
  paper.questions.forEach((q, k) => {
    add('question', k, q.question_rects, `Q${q.number}`)
    add('answer', k, q.answer_rects, `A${q.number}`)
  })
  add('orphan', null, paper.orphan_answers, null)

  function move(e) {
    if (!drag.current) return
    const pt = clientToPt(e.clientX, e.clientY, svgRef.current.getBoundingClientRect(), page)
    onResize(drag.current.sel, { [drag.current.edge]: drag.current.edge[0] === 'x' ? pt.x : pt.y })
  }

  return (
    <svg
      ref={svgRef}
      data-testid="overlay"
      viewBox={`0 0 ${page.width_px} ${page.height_px}`}
      className="absolute inset-0 w-full h-full"
      onClick={() => onSelect(null)}
    >
      {boxes.map(b => {
        const s = { list: b.list, q: b.q, i: b.i }
        const on = sameSel(sel, s)
        const inQuestion = sel && sel.list !== 'orphan' && b.q === sel.q
        return (
          <g key={`${b.list}-${b.q}-${b.i}`} data-kind={b.list} data-selected={on || undefined}>
            <rect
              {...b.box}
              fill={COLOUR[b.list]}
              fillOpacity={on ? 0.3 : inQuestion ? 0.2 : 0.1}
              stroke={COLOUR[b.list]}
              strokeWidth={on || inQuestion ? 4 : 2}
              strokeDasharray={b.list === 'orphan' ? '8 4' : undefined}
              style={{ cursor: 'pointer' }}
              onClick={e => { e.stopPropagation(); onSelect(s) }}
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
                onPointerUp={() => { drag.current = null }}
                onPointerCancel={() => { drag.current = null }}
              />
            ))}
          </g>
        )
      })}
    </svg>
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
  const [metadata, setMetadata] = useState(emptyMetadata)
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState(null)
  // After a confirm: the created paper's questions, awaiting the topic-review step.
  const [topicStep, setTopicStep] = useState(null)

  useEffect(() => {
    let live = true
    api.import.review(jobId)
      .then(r => {
        if (!live) return
        setReview(r)
        setMetadata(m => mergeSuggested(m, r.filename_metadata ?? {}))
        // Open on the first paper still undecided.
        const first = r.proposal.papers.findIndex(p => !p.outcome)
        if (first > 0) setPaperIdx(first)
      })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobId])

  latest.current = review

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
  const page = paper ? (paper.pages.find(p => p.page === pageNo) ?? paper.pages[0]) : null

  function choosePaper(i) {
    setPaperIdx(i)
    setPageNo(null)
    setSel(null)
  }

  function chooseQuestion(k) {
    setSel({ list: 'question', q: k, i: 0 })
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

  useEffect(() => {
    function onKey(e) {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      const t = e.target
      if (t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable)) return
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
      navigate('/admin/import')
      return
    }
    const next = papers.findIndex((p, i) => i !== paperIdx && !p.outcome)
    if (next >= 0) choosePaper(next)
  }

  async function handleConfirmPaper() {
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
        exam_type_id: metadata.exam_type_id,
        year: Number(metadata.year),
        paper_number: metadata.paper_number,
        is_premium: metadata.is_premium,
      })
      setTopicStep({ paperId: result.paper_id, questions: result.questions || [], jobStatus: result.job_status })
    } catch (e) {
      setConfirmError(e.message)
    } finally {
      setConfirming(false)
    }
  }

  async function handleSkipPaper() {
    if (!window.confirm(`Skip ${paperTitle(paper, paperIdx)}? It will not be imported.`)) return
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
      navigate('/admin/import')
    } catch (e) {
      setError(e.message)
      setHandoff(null)
    }
  }

  if (error && !review) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-6">
        <ErrorBanner message={error} />
        <Link to="/admin/import" className="text-blue-600 hover:underline text-sm">Back to import</Link>
      </div>
    )
  }
  if (!review) return <Spinner />

  if (topicStep) {
    return (
      <TopicReview
        paperId={topicStep.paperId}
        questions={topicStep.questions}
        subjectId={metadata.subject_id}
        streamId={metadata.stream_id}
        onDone={() => decided('confirmed', topicStep.jobStatus)}
        onCancel={() => decided('confirmed', topicStep.jobStatus)}
        cancelLabel="Skip topics (set them later in Manage Papers)"
      />
    )
  }

  const unrouted = review.proposal.unrouted ?? []
  const flaggedPage = p => p.needs_review

  return (
    <div className="px-4 py-4">
      <div className="flex items-center gap-4 mb-3">
        <Link to="/admin/import" className="text-sm text-blue-600 hover:underline">Back to import</Link>
        <h1 className="text-lg font-semibold text-gray-800 break-all">{review.filename}</h1>
        {review.edited && <span className="text-xs text-gray-500">edited</span>}
        {saveState !== 'idle' && (
          <span role="status" data-state={saveState} className={`text-xs ${saveState === 'error' ? 'text-red-600' : 'text-gray-500'}`}>
            {SAVE_LABEL[saveState]}
          </span>
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
                  <Overlay page={page} paper={paper} sel={sel} onSelect={setSel} onResize={onResize} />
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
                          <span className="font-medium">Question {q.number}</span>
                          {q.answer_rects.length === 0 && <span className="text-xs text-gray-500"> (no answer)</span>}
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
              {paper.questions.length === 0 && (
                <p className="w-52 mb-2 text-xs text-amber-800">
                  A paper without questions cannot be imported; skip it.
                </p>
              )}
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
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
