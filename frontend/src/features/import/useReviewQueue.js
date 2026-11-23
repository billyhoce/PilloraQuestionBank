import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import usePoll from './usePoll'

// How often the review queue looks for newly finished jobs.
export const REVIEW_POLL_MS = 10000

// The jobs waiting for an admin's decision (`review_ready`), kept fresh by polling so a job the
// worker finishes shows up without a reload. Shared by the import layout (its tab badge), the
// review queue page and the job review page ("next job"). With `enabled` false it does nothing (a
// page that already gets the queue from the layout still has to call the hook unconditionally).
export default function useReviewQueue({ enabled = true } = {}) {
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState(null)
  const [checkedAt, setCheckedAt] = useState(null)

  const apply = useCallback(res => {
    setJobs(res.jobs)
    setError(null)
    setCheckedAt(new Date())
  }, [])

  const refresh = useCallback(async () => {
    try {
      apply(await api.import.listJobs('review_ready'))
    } catch (e) {
      setError(e.message)
    }
  }, [apply])

  useEffect(() => {
    if (!enabled) return undefined
    let live = true
    api.import.listJobs('review_ready')
      .then(res => { if (live) apply(res) })
      .catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [enabled, apply])
  usePoll(refresh, REVIEW_POLL_MS, enabled)

  return { jobs, error, checkedAt, refresh }
}
