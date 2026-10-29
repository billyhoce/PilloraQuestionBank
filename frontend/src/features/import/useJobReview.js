import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { normalise, toEditPayload } from './proposalReducer'

export const SAVE_DELAY_MS = 800

const NOTHING = { review: null, matches: {}, proposals: {} }

// One ingest job under review: its proposal (questions by number, boxes in document order; saved
// so only with the first edit), the box edits saved 800 ms after the last change and on leaving,
// and its papers' links (`matches`) and automatic matches (`proposals`) by paper key. `jobId`
// null: nothing (a review page with no linked booklet in another job).
export default function useJobReview(jobId) {
  // Bumped to load the review again (after a change the server made to the proposal).
  const [version, setVersion] = useState(0)
  const key = jobId ? `${jobId}:${version}` : null
  // What was loaded, for which `key`: a review of another job (or an older load) is not shown.
  const [loaded, setLoaded] = useState({ key: null, ...NOTHING })
  const [error, setError] = useState(null)
  const [saveState, setSaveState] = useState('idle')
  const timer = useRef(null)
  const latest = useRef(null)

  useEffect(() => {
    if (!key) return undefined
    let live = true
    api.import.review(jobId)
      .then(r => {
        if (!live) return
        setLoaded({
          key,
          review: { ...r, proposal: { ...r.proposal, papers: r.proposal.papers.map(normalise) } },
          matches: r.matches ?? {},
          proposals: r.proposals ?? {},
        })
      })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [jobId, key])

  const current = loaded.key === key ? loaded : NOTHING
  const review = current.review
  useEffect(() => { latest.current = review })

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

  const update = (field, fn) => setLoaded(l => ({ ...l, [field]: fn(l[field]) }))
  const updateReview = fn => update('review', r => r && fn(r))

  // Store paper `index`'s edited version and queue a debounced save.
  function setPaper(index, next) {
    updateReview(r => ({
      ...r,
      edited: true,
      proposal: { ...r.proposal, papers: r.proposal.papers.map((p, i) => (i === index ? next : p)) },
    }))
    setSaveState('saving')
    clearTimeout(timer.current)
    timer.current = setTimeout(flush, SAVE_DELAY_MS)
  }

  // An edit still waiting for its debounce is saved now (the server crops the saved proposal).
  const flushPending = async () => { if (timer.current) await flush() }

  function markDecided(paperKey, outcome) {
    updateReview(r => ({
      ...r,
      proposal: { ...r.proposal, papers: r.proposal.papers.map(p => (p.key === paperKey ? { ...p, outcome } : p)) },
    }))
  }

  return {
    review, error, setError, saveState,
    matches: current.matches, setMatches: fn => update('matches', fn),
    proposals: current.proposals, setProposals: fn => update('proposals', fn),
    setPaper, flushPending, markDecided, reload: () => setVersion(v => v + 1),
  }
}
