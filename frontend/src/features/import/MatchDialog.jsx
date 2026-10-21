import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Modal from '../../components/Modal'
import Spinner from '../../components/Spinner'
import { Thumbnail } from './RectPreview'
import SchoolCombobox from './SchoolCombobox'
import { candidateQuery, coverageNote, detailsText, differences, locationText, metadataBody } from './pairing'

const SEARCH_DELAY_MS = 250

const PICKERS = [
  ['subject_id', 'Subject', 'Subjects', 'subjects'], ['stream_id', 'Stream', 'Streams', 'streams'],
  ['level_id', 'Level', 'Levels', 'levels'], ['exam_type_id', 'Exam type', 'Exam types', 'examTypes'],
]

const inputCls = 'w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

// Append or replace, for a bank paper that already has answers on some questions.
export function AttachModeChoice({ mode, onMode }) {
  return (
    <fieldset className="text-xs text-gray-700 space-y-1">
      <legend className="mb-1">Some of its questions already have answers:</legend>
      {['append', 'replace'].map(m => (
        <label key={m} className="flex items-center gap-2">
          <input type="radio" name="attach-mode" checked={mode === m} onChange={() => onMode(m)} />
          {m === 'append' ? 'Add to the existing answers' : 'Replace the existing answers'}
        </label>
      ))}
    </fieldset>
  )
}

function Candidate({ c, fields, refs, role, ownPreview, saving, choosing, onPair, onAttach, onChoose, onMode }) {
  const full = c.kind === 'bank' && c.answer_coverage === 'all'
  const note = coverageNote(c)
  const differ = differences(c, fields, refs)
  const answerOnly = role === 'answer_only'
  const btn = 'bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-3 py-1 text-xs font-medium'
  return (
    <li aria-disabled={full || undefined} className={`flex gap-3 rounded border p-2 text-xs ${full ? 'border-gray-200 bg-gray-50 text-gray-400' : 'border-gray-200'}`}>
      <div className="flex-1 min-w-0 space-y-0.5">
        <p className="font-medium">{locationText(c)}</p>
        <p>{detailsText(c.details, refs) || 'No details'}</p>
        {differ.length > 0 && (
          <p className="flex flex-wrap gap-1">
            {differ.map(d => <span key={d} className="rounded bg-amber-100 text-amber-900 px-1">{d}</span>)}
          </p>
        )}
        {c.partner && <p className="text-amber-800">This will unpair it from {c.partner.filename}</p>}
        {note && <p className={full ? '' : 'text-amber-800'}>{note}</p>}
      </div>
      <div className="w-48 shrink-0 grid grid-cols-2 gap-1 text-gray-600">
        <div>
          <p className="mb-0.5">{answerOnly ? 'First question' : 'First answer'}</p>
          <Thumbnail preview={c.preview} alt={answerOnly ? 'Candidate first question' : 'Candidate first answer'} />
        </div>
        <div>
          <p className="mb-0.5">{answerOnly ? 'First answer' : 'First question'}</p>
          <Thumbnail preview={ownPreview} alt={answerOnly ? "This paper's first answer" : "This paper's first question"} />
        </div>
      </div>
      {!full && (
        <div className="w-36 shrink-0 flex flex-col gap-2 items-start">
          {c.kind === 'pending' ? (
            <button type="button" className={btn} disabled={saving} onClick={() => onPair(c)}>Pair</button>
          ) : choosing ? (
            <>
              <AttachModeChoice mode={choosing.mode} onMode={onMode} />
              <button type="button" className={btn} disabled={saving} onClick={() => onAttach(c, choosing.mode)}>Attach answers</button>
            </>
          ) : (
            <button type="button" className={btn} disabled={saving}
              onClick={() => (c.answer_coverage === 'partial' ? onChoose(c) : onAttach(c, null))}>
              Attach
            </button>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * "Match this paper": search for the booklet a paper that needs a partner belongs with, by
 * ranking rather than filtering, then Pair it (a pending paper) or Attach it (a bank paper).
 *   jobId, paperKey, role - the paper being matched ('answer_only' or 'question')
 *   metadata       - its fields as the sidebar holds them; they pre-fill the search
 *   extractedSchool - the school read from its cover, shown while unresolved (searched as blank)
 *   refs           - the reference lists (useReferenceData)
 *   ownPreview     - its own first answer (answer-only) or question, { url, page?, rect? }, or null
 *   beforeSave     - optional async () => void, awaited before anything is saved
 *   onPaired(state, fields) - after Pair: the match route's { matches, proposal }, and the fields
 *                    saved on the paper ("Also update this paper's details"), else null
 *   onAttached(result)      - after Attach: the attach result plus the bank `paper_id`
 *   onClose
 */
export default function MatchDialog({
  jobId, paperKey, role, metadata, extractedSchool = null, refs, ownPreview = null, beforeSave, onPaired, onAttached, onClose,
}) {
  const [fields, setFields] = useState(() => ({
    subject_id: metadata.subject_id ?? null, stream_id: metadata.stream_id ?? null, level_id: metadata.level_id ?? null,
    school_id: metadata.school_id ?? null, new_school_name: metadata.new_school_name ?? null,
    exam_type_id: metadata.exam_type_id ?? null, year: metadata.year ?? '', paper_number: metadata.paper_number ?? '',
  }))
  const [updateDetails, setUpdateDetails] = useState(true)
  const [results, setResults] = useState(null) // { exact, best }
  const [choosing, setChoosing] = useState(null) // { paperId, mode } while asking append/replace
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    const t = setTimeout(() => {
      api.import.paperCandidates(jobId, paperKey, candidateQuery(fields))
        .then(r => { if (live) setResults(r) })
        .catch(e => { if (live) { setError(e.message); setResults({ exact: [], best: [] }) } })
    }, SEARCH_DELAY_MS)
    return () => { live = false; clearTimeout(t) }
  }, [jobId, paperKey, fields])

  const set = patch => {
    setChoosing(null)
    setFields(f => ({ ...f, ...patch }))
  }

  async function save(call) {
    setSaving(true)
    setError(null)
    try {
      await beforeSave?.()
      await call()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const pair = c => save(async () => {
    const state = await api.import.matchJobPaper(jobId, paperKey, c.ingest_paper_id, updateDetails ? metadataBody(fields) : undefined)
    onPaired(state, updateDetails ? fields : null)
  })

  const attach = (c, mode) => save(async () => {
    const result = await api.import.attachJobPaper(jobId, { key: paperKey, paper_id: c.paper_id, ...(mode && { mode }) })
    onAttached({ ...result, paper_id: c.paper_id })
  })

  const list = results && (results.exact.length ? ['Exact matches', results.exact] : results.best.length ? ['Best matches', results.best] : null)
  // The tick box applies to Pair only: an answer paper's own details are not kept after an attach.
  const canPair = !!list?.[1].some(c => c.kind === 'pending')
  return (
    <Modal isOpen onClose={onClose} title="Match this paper" wide>
      <div className="space-y-4">
        {!refs ? <Spinner size="sm" /> : (
          <fieldset className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <legend className="sr-only">Details to search by (blank means any)</legend>
            {PICKERS.map(([key, label, listLabel, refList]) => (
              <SchoolCombobox key={key} schools={refs[refList]} value={fields[key]} label={label} listLabel={listLabel}
                onChange={id => set({ [key]: id })} />
            ))}
            <SchoolCombobox schools={refs.schools} value={fields.school_id}
              onChange={id => set({ school_id: id, new_school_name: null })}
              onNewSchool={name => set({ school_id: null, new_school_name: name })}
              newName={fields.new_school_name} extractedName={extractedSchool} />
            <label className="block text-xs font-medium text-gray-600">
              Year
              <input type="number" value={fields.year} onChange={e => set({ year: e.target.value })} className={inputCls} />
            </label>
            <label className="block text-xs font-medium text-gray-600">
              Paper no.
              <input type="text" value={fields.paper_number} onChange={e => set({ paper_number: e.target.value })} className={inputCls} />
            </label>
          </fieldset>
        )}
        {canPair && (
          <div className="flex flex-wrap items-center gap-x-2 text-sm text-gray-700">
            <label className="flex items-center gap-2 select-none">
              <input type="checkbox" checked={updateDetails} onChange={e => setUpdateDetails(e.target.checked)} />
              Also update this paper&apos;s details
            </label>
            <span className="text-xs text-gray-500">when pairing; untick it if you only cleared fields to widen the search</span>
          </div>
        )}
        {error && <ErrorBanner message={error} />}
        {results === null ? (
          <div className="flex justify-center py-2"><Spinner size="sm" /></div>
        ) : !list ? (
          <p className="text-sm text-gray-500">No booklet matches these details.</p>
        ) : (
          <section>
            <h3 className="text-sm font-semibold text-gray-800 mb-1">{list[0]}</h3>
            {list[0] === 'Best matches' && (
              <p className="text-xs text-gray-500 mb-1">No booklet matches every field; these match the most.</p>
            )}
            <ul aria-label={list[0]} className="space-y-2">
              {list[1].map(c => (
                <Candidate
                  key={c.kind === 'bank' ? `b${c.paper_id}` : `p${c.ingest_paper_id}`}
                  c={c} fields={fields} refs={refs} role={role} ownPreview={ownPreview} saving={saving}
                  choosing={c.kind === 'bank' && choosing?.paperId === c.paper_id ? choosing : null}
                  onPair={pair} onAttach={attach}
                  onChoose={x => setChoosing({ paperId: x.paper_id, mode: 'append' })}
                  onMode={mode => setChoosing(ch => ({ ...ch, mode }))}
                />
              ))}
            </ul>
          </section>
        )}
      </div>
    </Modal>
  )
}
