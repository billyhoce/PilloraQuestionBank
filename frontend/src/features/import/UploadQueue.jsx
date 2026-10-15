import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import { UploadQueueContext } from './uploadQueueContext'

// The auto-import upload queue. It lives above the routes (App.jsx), so PDFs keep uploading while
// the admin moves between pages, and more can be dropped at any time: each file is its own entry,
// at most UPLOAD_CONCURRENCY transfer at once, the rest wait their turn.
//
// An entry is { id, file, name, size, status, progress, jobId, error }:
//   status 'waiting'   — not started yet (cancelling just drops it)
//          'uploading' — creating the job / sending to S3 / queueing it (cancelling aborts it and
//                        the API client cancels the half-made job)
//          'failed'    — kept, with its error, until retried or dismissed
// A finished upload leaves the queue — its job is on the server's job list from then on — and
// bumps `completed`, which pages watch to refresh that list.

export const UPLOAD_CONCURRENCY = 3

let seq = 0
const sameFile = (a, b) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified

export function UploadQueueProvider({ children, concurrency = UPLOAD_CONCURRENCY }) {
  // The list is state (what renders) mirrored in a ref (what the scheduler reads synchronously,
  // between renders, as transfers start and finish).
  const [items, setItems] = useState([])
  const itemsRef = useRef(items)
  const controllers = useRef(new Map())
  const [completed, setCompleted] = useState(0)

  const set = useCallback(next => {
    itemsRef.current = next
    setItems(next)
  }, [])
  const patch = useCallback((id, p) => set(itemsRef.current.map(it => (it.id === id ? { ...it, ...p } : it))), [set])
  const remove = useCallback(id => set(itemsRef.current.filter(it => it.id !== id)), [set])

  const pumpRef = useRef(() => {})
  const start = useCallback(item => {
    const controller = new AbortController()
    controllers.current.set(item.id, controller)
    patch(item.id, { status: 'uploading', progress: 0, error: null })
    api.import.uploadJob(item.file, fraction => patch(item.id, { progress: fraction }), {
      signal: controller.signal,
      onJob: jobId => patch(item.id, { jobId }),
    })
      .then(() => {
        setCompleted(c => c + 1)
        remove(item.id)
      })
      .catch(e => {
        if (e?.aborted) remove(item.id)
        else patch(item.id, { status: 'failed', error: e?.message || 'Upload failed', jobId: null })
      })
      .finally(() => {
        controllers.current.delete(item.id)
        pumpRef.current()
      })
  }, [patch, remove])

  const pump = useCallback(() => {
    let free = concurrency - itemsRef.current.filter(it => it.status === 'uploading').length
    for (const it of itemsRef.current) {
      if (free <= 0) break
      if (it.status === 'waiting') {
        start(it)
        free -= 1
      }
    }
  }, [concurrency, start])
  useEffect(() => { pumpRef.current = pump }, [pump])

  // Queue files; a file already waiting or uploading is not queued twice.
  // Returns { added, duplicates }.
  const add = useCallback(files => {
    const live = itemsRef.current.filter(it => it.status !== 'failed')
    const fresh = []
    let duplicates = 0
    for (const file of files) {
      if (live.some(it => sameFile(it.file, file)) || fresh.some(it => sameFile(it.file, file))) {
        duplicates += 1
        continue
      }
      seq += 1
      fresh.push({ id: `u${seq}`, file, name: file.name, size: file.size, status: 'waiting', progress: 0, jobId: null, error: null })
    }
    if (fresh.length) {
      set([...itemsRef.current, ...fresh])
      pump()
    }
    return { added: fresh.length, duplicates }
  }, [pump, set])

  const cancel = useCallback(id => {
    const it = itemsRef.current.find(x => x.id === id)
    if (!it) return
    if (it.status === 'uploading') controllers.current.get(id)?.abort()
    else remove(id)
  }, [remove])

  const cancelWaiting = useCallback(() => set(itemsRef.current.filter(it => it.status !== 'waiting')), [set])

  const retry = useCallback(id => {
    patch(id, { status: 'waiting', progress: 0, error: null })
    pump()
  }, [patch, pump])

  const dismiss = useCallback(id => remove(id), [remove])

  const busy = items.some(it => it.status !== 'failed')

  // Leaving the site mid-upload would strand those files: ask first.
  useEffect(() => {
    if (!busy) return undefined
    const warn = e => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [busy])

  // Signing out (the provider unmounting) stops every transfer.
  useEffect(() => {
    const live = controllers.current
    return () => live.forEach(c => c.abort())
  }, [])

  const value = useMemo(
    () => ({ items, busy, completed, add, cancel, cancelWaiting, retry, dismiss }),
    [items, busy, completed, add, cancel, cancelWaiting, retry, dismiss],
  )
  return <UploadQueueContext.Provider value={value}>{children}</UploadQueueContext.Provider>
}
