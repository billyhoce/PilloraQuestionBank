import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

export const PAGE_SIZE = 50

/**
 * Map a UI filter object to `api.questions.list` arguments.
 *
 * Exported because the Generate page's "Select All" needs the same mapping for
 * a one-off fetch outside the hook's own paging.
 */
export function filtersToListArgs(filters, page) {
  return {
    subject_id: filters.subject_id || undefined,
    stream_id: filters.stream_id || undefined,
    level_id: filters.level_id || undefined,
    school_id: filters.school_id || undefined,
    exam_type_id: filters.exam_type_id || undefined,
    year: filters.year || undefined,
    paper_number: filters.paper_number || undefined,
    topic_ids: filters.topic_ids,
    exclusive: filters.exclusive,
    tag_ids: filters.tag_ids,
    search: filters.search || undefined,
    page,
    page_size: PAGE_SIZE,
  }
}

/**
 * The paginated question-search state machine shared by Browse and Generate.
 *
 * Both pages show the same filtered, "Load more" list of questions; only where
 * their filters *live* differs — Browse keeps them in the URL, Generate in local
 * state. So the hook takes the filters as input and owns everything downstream:
 * fetching on change, aborting the in-flight request, paging, and de-duplicating
 * appended pages by id.
 *
 * Returns `setItems` as well, so a caller can patch a row in place (e.g. after
 * editing a question's tags) without refetching the page.
 */
export function useQuestionSearch(filters) {
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    setItems([])
    setPage(1)
    setLoading(true)
    setError(null)

    api.questions.list(filtersToListArgs(filters, 1), controller.signal)
      .then(res => {
        if (cancelled) return
        setItems(res.items || [])
        setTotal(res.total || 0)
      })
      .catch(e => {
        if (cancelled || e?.name === 'AbortError') return
        setError(e?.message || 'Failed to load questions')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true; controller.abort() }
    // filterKey is the value-identity of `filters`; depending on the object
    // itself would refetch on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  const loadMore = useCallback(async () => {
    if (loadingMore) return
    const nextPage = page + 1
    setLoadingMore(true)
    setError(null)
    try {
      const res = await api.questions.list(filtersToListArgs(filters, nextPage))
      setItems(prev => {
        const seen = new Set(prev.map(it => it.id))
        return [...prev, ...(res.items || []).filter(it => !seen.has(it.id))]
      })
      setTotal(res.total || 0)
      setPage(nextPage)
    } catch (e) {
      setError(e?.message || 'Failed to load more questions')
    } finally {
      setLoadingMore(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, page, loadingMore])

  return { items, setItems, total, page, loading, loadingMore, error, setError, loadMore }
}
