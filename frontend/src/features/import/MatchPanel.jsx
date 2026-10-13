import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { rectToPx } from './reviewGeometry'

const num = n => Number(String(n).trim())

const SELECTS = [
  ['subject_id', 'Subject', 'subjects'], ['stream_id', 'Stream', 'streams'], ['level_id', 'Level', 'levels'],
  ['school_id', 'School', 'schools'], ['exam_type_id', 'Exam type', 'examTypes'],
]

// The part of a review page image inside `rect` (PDF points), scaled to fit its box.
function RectPreview({ url, page, rect, alt }) {
  const box = rectToPx(rect, page)
  return (
    <div className="relative overflow-hidden border border-gray-300 bg-white" style={{ aspectRatio: `${box.width} / ${box.height}` }}>
      <img
        src={url}
        alt={alt}
        className="absolute max-w-none"
        style={{
          width: `${(page.width_px / box.width) * 100}%`,
          left: `${(-box.x / box.width) * 100}%`,
          top: `${(-box.y / box.height) * 100}%`,
        }}
      />
    </div>
  )
}

// This paper's first answer, as { number, url, page, rect } (null when it has none with a page image).
function firstAnswer(paper) {
  for (const q of paper.questions) {
    for (const rect of q.answer_rects) {
      const page = paper.pages.find(p => p.page === rect.page)
      if (page?.url) return { number: q.number, url: page.url, page, rect }
    }
  }
  return null
}

const metaText = m => [m.year, m.paper_number && `Paper ${m.paper_number}`].filter(Boolean).join(' ')

// Match an answer-only paper to its question paper by hand. Filters start from the paper's own
// metadata; candidates are the confirmed papers (GET /api/papers) and the pending question papers of
// other review-ready jobs. Selecting a confirmed paper enables Attach (append / replace prompt as
// before, unless the answers have nowhere to clash); selecting a pending one links the two ingest
// papers instead (they are settled together when the question paper is confirmed).
export default function MatchPanel({ jobId, paper, metadata, refs, link, onLink, onFlush, onAttached, onSkip, busy }) {
  const [filters, setFilters] = useState(() => ({
    subject_id: metadata.subject_id ?? '', stream_id: metadata.stream_id ?? '', level_id: metadata.level_id ?? '',
    school_id: metadata.school_id ?? '', exam_type_id: metadata.exam_type_id ?? '',
    year: metadata.year ?? '', paper_number: metadata.paper_number ?? '',
  }))
  const [candidates, setCandidates] = useState(null) // { confirmed, pending }
  const [selected, setSelected] = useState(null) // { kind: 'confirmed' | 'pending', ...item }
  const [preview, setPreview] = useState(null) // the selected confirmed paper's first question image
  const [paperId, setPaperId] = useState('')
  const [choice, setChoice] = useState(null) // { mode, count } while asking
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    let live = true
    Promise.all([
      api.papers.list({ ...filters, page_size: 50 }),
      api.import.pendingPapers({ ...filters, exclude_job_id: jobId }),
    ])
      .then(([confirmed, pending]) => {
        if (!live) return
        const wanted = String(filters.paper_number).trim().toLowerCase()
        setCandidates({
          // GET /api/papers has no paper-number filter, so narrow it here.
          confirmed: confirmed.items.filter(p => !wanted || String(p.paper_number).trim().toLowerCase() === wanted),
          pending,
        })
      })
      .catch(e => { if (live) { setError(e.message); setCandidates({ confirmed: [], pending: [] }) } })
    return () => { live = false }
  }, [filters, jobId])

  async function select(kind, item) {
    setSelected({ kind, ...item })
    setChoice(null)
    setPreview(null)
    if (kind === 'confirmed') {
      setPaperId(String(item.id))
      try {
        const full = await api.papers.get(item.id)
        const first = [...full.questions].sort((a, b) => a.question_number - b.question_number)[0]
        const pg = first?.pages.filter(p => p.page_type === 'question').sort((a, b) => a.page_order - b.page_order)[0]
        setPreview(pg ? { number: first.question_number, url: pg.url } : { number: null, url: null })
      } catch {
        setPreview({ number: null, url: null })
      }
    }
  }

  async function submit(mode) {
    const r = await api.import.attachJobPaper(jobId, { key: paper.key, paper_id: Number(paperId), ...(mode ? { mode } : {}) })
    setChoice(null)
    setResult(r)
  }

  async function handleAttach() {
    setLoading(true)
    setError(null)
    try {
      await onFlush() // the server crops the saved proposal, so a pending edit goes first
      if (choice) {
        await submit(choice.mode)
        return
      }
      const target = await api.papers.get(Number(paperId))
      const withAnswers = new Set(
        target.questions.filter(q => q.pages.some(p => p.page_type === 'answer')).map(q => Number(q.question_number)),
      )
      const count = paper.questions.filter(q => q.answer_rects.length > 0 && withAnswers.has(num(q.number))).length
      if (count > 0) setChoice({ mode: 'append', count })
      else await submit(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleLink() {
    setLoading(true)
    setError(null)
    try {
      const r = await api.import.matchJobPaper(jobId, paper.key, selected.ingest_paper_id)
      onLink(r.matches)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleUnlink() {
    setLoading(true)
    setError(null)
    try {
      await api.import.unmatchJobPaper(jobId, paper.key)
      onLink(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const setFilter = (k, v) => {
    setCandidates(null) // reloads below
    setFilters(f => ({ ...f, [k]: v }))
  }
  const answer = firstAnswer(paper)
  const pendingPreview = selected?.kind === 'pending' ? selected.preview : null

  if (result) {
    return (
      <div role="status" className="w-52 shrink-0 flex flex-col gap-2 text-sm">
        <p className="text-green-800">
          Attached answers for question{result.attached.length === 1 ? '' : 's'} {result.attached.join(', ')} to paper {paperId}.
        </p>
        {result.unmatched.length > 0 && (
          <p className="text-amber-800">
            Not attached (no such question in the paper): {result.unmatched.join(', ')}.
          </p>
        )}
        <button
          type="button"
          onClick={() => onAttached(result.job_status)}
          className="bg-blue-600 hover:bg-blue-700 text-white rounded px-4 py-2 text-sm font-medium"
        >
          Continue
        </button>
      </div>
    )
  }

  const inputCls = 'w-full border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500'
  const candidateCls = on => `block w-full text-left rounded border px-2 py-1 text-xs ${on ? 'border-blue-600 bg-blue-50' : 'border-gray-200 bg-white'}`
  return (
    <div className="w-80 shrink-0 flex flex-col gap-3 p-4 bg-white border-l border-gray-200 max-h-[80vh] overflow-y-auto">
      <h2 className="text-sm font-semibold text-gray-800">Match to paper…</h2>

      {link && (
        <div role="status" className="text-xs bg-blue-50 border border-blue-200 rounded px-2 py-1.5 space-y-1">
          <p>Linked to {link.filename} {link.paper_key}. Confirming that question paper will bring these answers in.</p>
          <button type="button" onClick={handleUnlink} disabled={loading || busy} className="text-blue-700 hover:underline disabled:opacity-50">
            Unlink
          </button>
        </div>
      )}

      <fieldset className="grid grid-cols-2 gap-2">
        <legend className="sr-only">Filters</legend>
        {SELECTS.map(([key, label, list]) => (
          <label key={key} className="block text-xs text-gray-600">
            {label}
            <select value={filters[key]} onChange={e => setFilter(key, e.target.value)} className={inputCls}>
              <option value="">Any</option>
              {(refs?.[list] ?? []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </label>
        ))}
        <label className="block text-xs text-gray-600">
          Year
          <input type="number" value={filters.year} onChange={e => setFilter('year', e.target.value)} className={inputCls} />
        </label>
        <label className="block text-xs text-gray-600">
          Paper no.
          <input type="text" value={filters.paper_number} onChange={e => setFilter('paper_number', e.target.value)} className={inputCls} />
        </label>
      </fieldset>

      <div aria-label="Candidates" role="region" className="space-y-1">
        {candidates === null ? (
          <div className="flex justify-center py-2"><Spinner size="sm" /></div>
        ) : candidates.confirmed.length + candidates.pending.length === 0 ? (
          <p className="text-xs text-gray-500">No paper matches these filters.</p>
        ) : (
          <>
            {candidates.confirmed.map(p => (
              <button
                key={`c${p.id}`} type="button" aria-pressed={selected?.kind === 'confirmed' && selected.id === p.id}
                onClick={() => select('confirmed', p)} className={candidateCls(selected?.kind === 'confirmed' && selected.id === p.id)}
              >
                <span className="font-medium">Paper {p.id}</span> {p.school_name} {p.year} {p.level_name} {p.subject_name}
                {p.paper_number ? ` P${p.paper_number}` : ''}
              </button>
            ))}
            {candidates.pending.map(p => (
              <button
                key={`p${p.ingest_paper_id}`} type="button"
                aria-pressed={selected?.kind === 'pending' && selected.ingest_paper_id === p.ingest_paper_id}
                onClick={() => select('pending', p)}
                className={candidateCls(selected?.kind === 'pending' && selected.ingest_paper_id === p.ingest_paper_id)}
              >
                <span className="font-medium">Pending: {p.filename}</span> {p.paper_key} {metaText(p.metadata)}
              </button>
            ))}
          </>
        )}
      </div>

      {selected && (
        <div aria-label="Preview" role="region" className="grid grid-cols-2 gap-2 text-xs text-gray-600">
          <div>
            <p className="mb-1">First question</p>
            {selected.kind === 'confirmed' ? (
              preview === null ? <Spinner size="sm" />
                : preview.url ? <img src={preview.url} alt="Candidate first question" className="w-full border border-gray-300" />
                  : <p className="text-gray-500">No question image.</p>
            ) : pendingPreview ? (
              <RectPreview url={pendingPreview.url} page={pendingPreview.page} rect={pendingPreview.rect} alt="Candidate first question" />
            ) : <p className="text-gray-500">No question image.</p>}
          </div>
          <div>
            <p className="mb-1">First answer{answer ? ` (${answer.number})` : ''}</p>
            {answer
              ? <RectPreview url={answer.url} page={answer.page} rect={answer.rect} alt="This paper's first answer" />
              : <p className="text-gray-500">No answer image.</p>}
          </div>
        </div>
      )}

      <div>
        <label htmlFor="attach-paper-id" className="block text-xs font-medium text-gray-600 mb-1">Paper id</label>
        <input
          id="attach-paper-id"
          type="number"
          min="1"
          value={paperId}
          onChange={e => { setPaperId(e.target.value); setChoice(null); if (selected?.kind === 'confirmed' && String(selected.id) !== e.target.value) setSelected(null) }}
          className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      {choice && (
        <fieldset className="text-xs text-gray-700 space-y-1">
          <legend className="mb-1">
            {choice.count} question{choice.count === 1 ? ' already has' : 's already have'} answers:
          </legend>
          {['append', 'replace'].map(m => (
            <label key={m} className="flex items-center gap-2">
              <input type="radio" name="attach-mode" checked={choice.mode === m} onChange={() => setChoice({ ...choice, mode: m })} />
              {m === 'append' ? 'Add to the existing answers' : 'Replace the existing answers'}
            </label>
          ))}
        </fieldset>
      )}
      {error && <ErrorBanner message={error} />}
      {selected?.kind === 'pending' ? (
        <button
          type="button"
          onClick={handleLink}
          disabled={loading || busy || paper.questions.length === 0}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center justify-center gap-2"
        >
          {loading && <Spinner size="sm" />}
          Link to this paper
        </button>
      ) : (
        <button
          type="button"
          onClick={handleAttach}
          disabled={!(Number(paperId) > 0) || loading || busy || paper.questions.length === 0}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center justify-center gap-2"
        >
          {loading && <Spinner size="sm" />}
          {choice ? 'Attach answers' : 'Attach to paper…'}
        </button>
      )}
      <button type="button" onClick={onSkip} disabled={loading || busy} className="text-xs text-red-600 hover:text-red-700 text-center disabled:opacity-50">
        Skip this paper
      </button>
    </div>
  )
}
