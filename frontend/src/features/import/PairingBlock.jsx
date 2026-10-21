import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import MatchDialog, { AttachModeChoice } from './MatchDialog'
import { candidateQuery, detailsText, firstRect, pairingState } from './pairing'

const COUNT_DELAY_MS = 400

const describePaper = p =>
  `${p.school} ${p.year} ${p.level} ${p.subject}${p.paper_number ? ` Paper ${p.paper_number}` : ''} (paper ${p.id})`

const linkBtn = 'text-blue-700 hover:underline disabled:opacity-50'

// What an attach did, until the admin carries on.
function AttachResult({ result, onContinue }) {
  return (
    <div role="status" className="space-y-2">
      <p className="text-green-800">
        Attached answers for question{result.attached.length === 1 ? '' : 's'} {result.attached.join(', ')} to paper {result.paper_id}.
      </p>
      {result.unmatched.length > 0 && (
        <p className="text-amber-800">Not attached (no such question in the paper): {result.unmatched.join(', ')}.</p>
      )}
      <button type="button" onClick={onContinue}
        className="bg-blue-600 hover:bg-blue-700 text-white rounded px-4 py-2 text-sm font-medium">
        Continue
      </button>
    </div>
  )
}

/**
 * The review page's Pairing block, on a paper that needs a partner (an answer-only paper, or a
 * question paper whose booklet had no answers) or that has one. Three states (see pairingState):
 * no partner ("No match found" / "N possible matches", Match this paper…), linked to a pending
 * paper (Change match…, Unmatch) and, for an answer-only paper, a proposed bank paper (Attach…,
 * Change match…, Not this one). Answers go on by question number.
 *   onMatched(state, fields?) - the paper's new { matches, proposal } after a pair, Unmatch or
 *                    "Not this one"; `fields` are the details a pair saved on the paper, if any
 *   onAttached(jobStatus)    - after an attach, once the admin has read the result
 *   beforeSave     - optional async () => void, awaited before anything is saved
 */
export default function PairingBlock({
  jobId, paper, link, proposal, metadata, extractedSchool = null, refs, busy = false, beforeSave, onMatched, onAttached,
}) {
  const state = pairingState({ link, proposal })
  const [count, setCount] = useState(null) // exact matches for the paper's details, while unpaired
  const [dialog, setDialog] = useState(false)
  const [choosing, setChoosing] = useState(null) // the append/replace answer for a proposed paper
  const [result, setResult] = useState(null) // an attach's result
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const answerOnly = paper.role === 'answer_only'
  const query = JSON.stringify(candidateQuery(metadata))

  useEffect(() => {
    if (state !== 'none') return undefined
    let live = true
    const t = setTimeout(() => {
      api.import.paperCandidates(jobId, paper.key, JSON.parse(query))
        .then(r => { if (live) setCount(r.exact.length) })
        .catch(() => { if (live) setCount(null) })
    }, COUNT_DELAY_MS)
    return () => { live = false; clearTimeout(t) }
  }, [jobId, paper.key, query, state])

  async function run(call) {
    setSaving(true)
    setError(null)
    try {
      await call()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const rematch = call => run(async () => onMatched(await call(jobId, paper.key)))

  const attachProposed = mode => run(async () => {
    await beforeSave?.()
    const id = proposal.paper.id
    const r = await api.import.attachJobPaper(jobId, { key: paper.key, paper_id: id, ...(mode && { mode }) })
    setResult({ ...r, paper_id: id })
  })

  const box = 'w-52 mb-2 text-xs border rounded px-2 py-1.5 space-y-1'
  if (result) {
    return <div className={`${box} bg-green-50 border-green-200`}><AttachResult result={result} onContinue={() => onAttached(result.job_status)} /></div>
  }
  const disabled = saving || busy
  return (
    <section aria-label="Pairing" className={`${box} ${state === 'none' ? 'bg-amber-50 border-amber-200' : 'bg-blue-50 border-blue-200'}`}>
      {state === 'linked' && (
        <>
          <p>
            Paired with {link.job_id === jobId ? 'this file' : link.filename} ({link.paper_key}).{' '}
            {answerOnly ? 'Confirming that question paper brings these answers in.' : 'Its answers are attached when you confirm.'}
          </p>
          {link.details && <p className="text-gray-700">{detailsText(link.details, refs)}</p>}
          <p className="text-gray-500">{link.matched_by === 'auto' ? 'matched automatically' : 'matched by an admin'}</p>
          <p className="flex gap-3">
            <button type="button" className={linkBtn} disabled={disabled} onClick={() => setDialog(true)}>Change match…</button>
            <button type="button" className={linkBtn} disabled={disabled} onClick={() => rematch(api.import.unmatchJobPaper)}>Unmatch</button>
          </p>
        </>
      )}
      {state === 'proposed' && (
        <>
          <p>Answers match {describePaper(proposal.paper)}.</p>
          {choosing ? (
            <>
              <AttachModeChoice mode={choosing} onMode={setChoosing} />
              <button type="button" className={linkBtn} disabled={disabled} onClick={() => attachProposed(choosing)}>Attach answers</button>
            </>
          ) : (
            <p className="flex flex-wrap gap-x-3">
              <button type="button" className={linkBtn} disabled={disabled}
                onClick={() => (proposal.paper.answer_coverage === 'partial' ? setChoosing('append') : attachProposed(null))}>
                Attach…
              </button>
              <button type="button" className={linkBtn} disabled={disabled} onClick={() => setDialog(true)}>Change match…</button>
              <button type="button" className={linkBtn} disabled={disabled} onClick={() => rematch(api.import.rejectProposedPaper)}>Not this one</button>
            </p>
          )}
        </>
      )}
      {state === 'none' && (
        <>
          <p>
            {count === null ? 'Searching…'
              : count === 0 ? 'No match found'
                : `${count} possible match${count === 1 ? '' : 'es'}`}
          </p>
          <button type="button" className={linkBtn} disabled={disabled} onClick={() => setDialog(true)}>Match this paper…</button>
        </>
      )}
      {saving && <Spinner size="sm" />}
      {error && <ErrorBanner message={error} />}
      {dialog && (
        <MatchDialog
          jobId={jobId} paperKey={paper.key} role={paper.role ?? 'question'} metadata={metadata}
          extractedSchool={extractedSchool} refs={refs}
          ownPreview={firstRect(paper, answerOnly ? 'answer_rects' : 'question_rects')}
          beforeSave={beforeSave}
          onPaired={(s, fields) => { setDialog(false); onMatched(s, fields) }}
          onAttached={r => { setDialog(false); setResult(r) }}
          onClose={() => setDialog(false)}
        />
      )}
    </section>
  )
}
