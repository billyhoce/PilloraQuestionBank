import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { firstPageOf, rectToPx, rectsOnPage } from './reviewGeometry'
import { startManualImport } from './manualHandoff'

function paperTitle(paper, i) {
  return paper.label ? `${paper.label}${paper.answer_label ? ` / ${paper.answer_label}` : ''}` : `Answers ${paper.answer_label ?? i + 1}`
}

function Overlay({ page, paper, selected }) {
  const boxes = []
  paper.questions.forEach(q => {
    rectsOnPage(q.question_rects, page.page).forEach((r, i) =>
      boxes.push({ key: `q${q.number}-${i}`, kind: 'question', number: q.number, box: rectToPx(r, page), on: q.number === selected }))
    rectsOnPage(q.answer_rects, page.page).forEach((r, i) =>
      boxes.push({ key: `a${q.number}-${i}`, kind: 'answer', number: q.number, box: rectToPx(r, page), on: q.number === selected }))
  })
  rectsOnPage(paper.orphan_answers, page.page).forEach((r, i) =>
    boxes.push({ key: `o-${i}`, kind: 'orphan', number: null, box: rectToPx(r, page), on: false }))
  const colour = { question: '#2563eb', answer: '#16a34a', orphan: '#6b7280' }
  return (
    <svg
      data-testid="overlay"
      viewBox={`0 0 ${page.width_px} ${page.height_px}`}
      className="absolute inset-0 w-full h-full"
    >
      {boxes.map(b => (
        <g key={b.key} data-kind={b.kind}>
          <rect
            {...b.box}
            fill={colour[b.kind]}
            fillOpacity={b.on ? 0.25 : 0.1}
            stroke={colour[b.kind]}
            strokeWidth={b.on ? 4 : 2}
            strokeDasharray={b.kind === 'orphan' ? '8 4' : undefined}
          />
          {b.number != null && (
            <text x={b.box.x + 6} y={b.box.y + 22} fontSize="20" fill={colour[b.kind]}>
              {b.kind === 'answer' ? `A${b.number}` : `Q${b.number}`}
            </text>
          )}
        </g>
      ))}
    </svg>
  )
}

export default function ReviewPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [review, setReview] = useState(null)
  const [error, setError] = useState(null)
  const [paperIdx, setPaperIdx] = useState(0)
  const [pageNo, setPageNo] = useState(null)
  const [selected, setSelected] = useState(null)
  const [handoff, setHandoff] = useState(null)

  useEffect(() => {
    let live = true
    api.import.review(jobId)
      .then(r => { if (live) setReview(r) })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobId])

  const papers = review?.proposal.papers ?? []
  const paper = papers[paperIdx]
  const page = paper ? (paper.pages.find(p => p.page === pageNo) ?? paper.pages[0]) : null

  function choosePaper(i) {
    setPaperIdx(i)
    setPageNo(null)
    setSelected(null)
  }

  function chooseQuestion(q) {
    setSelected(q.number)
    const p = firstPageOf(q)
    if (p != null) setPageNo(p)
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

  const unrouted = review.proposal.unrouted ?? []
  const flaggedPage = p => p.needs_review

  return (
    <div className="px-4 py-4">
      <div className="flex items-center gap-4 mb-3">
        <Link to="/admin/import" className="text-sm text-blue-600 hover:underline">Back to import</Link>
        <h1 className="text-lg font-semibold text-gray-800 break-all">{review.filename}</h1>
        {review.edited && <span className="text-xs text-gray-500">edited</span>}
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
                  <Overlay page={page} paper={paper} selected={selected} />
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
                {paper.questions.map(q => (
                  <li key={q.number}>
                    <button
                      type="button"
                      data-flagged={q.flags.length > 0 || undefined}
                      aria-pressed={selected === q.number}
                      onClick={() => chooseQuestion(q)}
                      className={`w-full text-left text-sm rounded border px-2 py-1 ${
                        selected === q.number ? 'border-blue-600 bg-blue-50' : q.flags.length ? 'border-amber-300 bg-amber-50' : 'border-gray-200'
                      }`}
                    >
                      <span className="font-medium">Question {q.number}</span>
                      {q.answer_rects.length === 0 && <span className="text-xs text-gray-500"> (no answer)</span>}
                      {q.flags.map(f => (
                        <span key={f} className="block text-xs text-amber-800">{f}</span>
                      ))}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {paper.orphan_answers.length > 0 && (
              <p className="mt-2 text-xs text-gray-600">
                {paper.orphan_answers.length} answer rectangle{paper.orphan_answers.length === 1 ? '' : 's'} not matched to a question (grey, dashed).
              </p>
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
