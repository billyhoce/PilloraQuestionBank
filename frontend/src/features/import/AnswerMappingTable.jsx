import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { answersOn, byNumber, mappingWarnings, moveAnswer, startMapping } from './answerMapping'
import { Thumbnail } from './RectPreview'

const btn = 'rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50'

// One answer going onto a question: its thumbnail and where it goes ('' = not placed).
function AnswerChip({ answer, questions, value, onMove }) {
  return (
    <div className="w-28 space-y-1">
      <Thumbnail preview={answer.preview} alt={`Answer ${answer.label}`} />
      <div className="text-[11px] text-gray-600">
        <span aria-hidden="true">Answer {answer.label} →</span>
        <select aria-label={`Answer ${answer.label} goes onto`} value={value ?? ''}
          onChange={e => onMove(answer.label, e.target.value || null)}
          className="ml-1 border border-gray-300 rounded text-[11px]">
          {questions.map(q => <option key={q.label} value={q.label}>Q{q.label}</option>)}
          <option value="">Not placed</option>
        </select>
      </div>
    </div>
  )
}

/**
 * The answer mapping table (#92): each question of a pair beside the answers that will go onto
 * it, pre-filled by number (or by the pair's stored mapping), with thumbnails of both. The admin
 * can change any answer's question, or shift all answers by ±N; warnings for questions left with
 * no answers and answers left with no question update as rows change. Answers inside one booklet
 * are fixed with the answer-box editor instead.
 *   jobId, paperKey - the paper being paired (either role)
 *   target    - { ingest_paper_id } (a pending booklet), { paper_id } (a bank paper), or null for
 *               the paper's current link (GET .../papers/{key}/answer-map)
 *   saveLabel - the save button ("Pair", "Attach answers", "Save")
 *   onSave(mapping) - { answer label: question label | null }, every answer named
 *   onCancel, cancelLabel
 *   saving    - disables the buttons while the parent saves
 *   children  - shown above the buttons (e.g. append or replace)
 */
export default function AnswerMappingTable({
  jobId, paperKey, target, saveLabel, onSave, onCancel, cancelLabel = 'Back', saving = false, children,
}) {
  const [table, setTable] = useState(null) // { questions, answers }
  const [mapping, setMapping] = useState(null)
  const [shift, setShift] = useState('0')
  const [error, setError] = useState(null)
  const targetKey = JSON.stringify(target ?? null)

  useEffect(() => {
    let live = true
    api.import.answerMappingTable(jobId, paperKey, JSON.parse(targetKey))
      .then(t => {
        if (!live) return
        setTable(t)
        setMapping(startMapping(t.questions, t.answers, t.mapping))
      })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobId, paperKey, targetKey])

  if (error) {
    return (
      <div className="space-y-2">
        <ErrorBanner message={error} />
        <button type="button" onClick={onCancel} className={`${btn} border border-gray-300`}>{cancelLabel}</button>
      </div>
    )
  }
  if (!table) return <div className="flex justify-center py-2"><Spinner size="sm" /></div>

  const { questions, answers } = table
  const labels = new Set(questions.map(q => q.label))
  const unplaced = answers.filter(a => !labels.has(mapping[a.label]))
  const warnings = mappingWarnings(mapping, questions)
  const move = (answer, question) => setMapping(m => moveAnswer(m, answer, question))
  const chips = list => (
    <div className="flex flex-wrap gap-2">
      {list.map(a => <AnswerChip key={a.label} answer={a} questions={questions} value={mapping[a.label]} onMove={move} />)}
    </div>
  )

  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-700">Check which answers go onto which questions.</p>
      <div className="flex items-center gap-2 text-xs text-gray-700">
        <label className="flex items-center gap-2">
          Shift all answers by
          <input type="number" value={shift} onChange={e => setShift(e.target.value)}
            className="w-16 border border-gray-300 rounded px-1 py-0.5" />
        </label>
        <button type="button" className="text-blue-700 hover:underline"
          onClick={() => setMapping(byNumber(questions, answers, Number(shift) || 0))}>
          Apply
        </button>
      </div>
      <div className="max-h-[50vh] overflow-y-auto border border-gray-200 rounded">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-600">
            <tr><th className="p-1 text-left">Question</th><th className="p-1 text-left">Answers going onto it</th></tr>
          </thead>
          <tbody>
            {questions.map(q => {
              const on = answersOn(mapping, answers, q.label)
              return (
                <tr key={q.label} aria-label={`Q${q.label}`} className="border-t border-gray-100 align-top">
                  <th scope="row" className="p-1 w-32 text-left font-medium">
                    <p className="mb-0.5">Q{q.label}</p>
                    <Thumbnail preview={q.preview} alt={`Question ${q.label}`} />
                  </th>
                  <td className="p-1">
                    {on.length ? chips(on)
                      : q.answered ? <p className="text-gray-500">Has answers of its own</p>
                        : <p className="text-amber-800">No answers</p>}
                  </td>
                </tr>
              )
            })}
            {unplaced.length > 0 && (
              <tr aria-label="Not placed" className="border-t border-gray-200 bg-amber-50 align-top">
                <th scope="row" className="p-1 text-left font-medium">Not placed</th>
                <td className="p-1">{chips(unplaced)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {warnings.length > 0 && (
        <ul aria-label="Warnings" className="text-xs text-amber-800 space-y-0.5">
          {warnings.map(w => <li key={w}>{w}</li>)}
        </ul>
      )}
      {children}
      <div className="flex justify-end gap-2">
        <button type="button" disabled={saving} onClick={onCancel} className={`${btn} border border-gray-300`}>{cancelLabel}</button>
        <button type="button" disabled={saving} onClick={() => onSave(mapping)}
          className={`${btn} bg-blue-600 hover:bg-blue-700 text-white`}>
          {saveLabel}
        </button>
      </div>
    </div>
  )
}
