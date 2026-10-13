import { useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'

const num = n => Number(String(n).trim())

// Attach an answer-only paper's answers to an existing paper, by paper id. The target paper is
// fetched first: if any question that would receive answers already has answer pages, the admin
// chooses append (default) or replace; otherwise the server's default (replace) applies unprompted.
export default function AttachPanel({ jobId, paper, onFlush, onAttached, onSkip, busy }) {
  const [paperId, setPaperId] = useState('')
  const [choice, setChoice] = useState(null) // { mode, count } while asking
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

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

  return (
    <div className="w-52 shrink-0 flex flex-col gap-3 p-4 bg-white border-l border-gray-200">
      <div>
        <label htmlFor="attach-paper-id" className="block text-xs font-medium text-gray-600 mb-1">Paper id</label>
        <input
          id="attach-paper-id"
          type="number"
          min="1"
          value={paperId}
          onChange={e => { setPaperId(e.target.value); setChoice(null) }}
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
      <button
        type="button"
        onClick={handleAttach}
        disabled={!(Number(paperId) > 0) || loading || busy || paper.questions.length === 0}
        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center justify-center gap-2"
      >
        {loading && <Spinner size="sm" />}
        {choice ? 'Attach answers' : 'Attach to paper…'}
      </button>
      <button type="button" onClick={onSkip} disabled={loading || busy} className="text-xs text-red-600 hover:text-red-700 text-center disabled:opacity-50">
        Skip this paper
      </button>
    </div>
  )
}
