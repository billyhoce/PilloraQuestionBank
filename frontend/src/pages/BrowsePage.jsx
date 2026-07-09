import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'
import FilterBar from '../components/browse/FilterBar'
import QuestionCard from '../components/browse/QuestionCard'
import QuestionDetailModal from '../components/browse/QuestionDetailModal'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'

const PAGE_SIZE = 50

const SINGLE_KEYS = ['level_id', 'stream_id', 'subject_id', 'school_id', 'exam_type_id', 'year']

function filtersFromParams(params) {
  return {
    level_id: params.get('level_id') || '',
    stream_id: params.get('stream_id') || '',
    subject_id: params.get('subject_id') || '',
    school_id: params.get('school_id') || '',
    exam_type_id: params.get('exam_type_id') || '',
    year: params.get('year') || '',
    topic_ids: params.getAll('topic_ids').map(v => Number(v)).filter(n => Number.isFinite(n)),
    exclusive: params.get('exclusive') === '1',
    search: params.get('kw') || '',
  }
}

function paramsFromFilters(filters) {
  const p = new URLSearchParams()
  for (const k of SINGLE_KEYS) {
    if (filters[k] !== '' && filters[k] != null) p.set(k, filters[k])
  }
  for (const id of filters.topic_ids || []) p.append('topic_ids', id)
  if (filters.exclusive && (filters.topic_ids || []).length > 0) p.set('exclusive', '1')
  if (filters.search) p.set('kw', filters.search)
  return p
}

export default function BrowsePage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromParams(searchParams), [searchParams])
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [selectedItem, setSelectedItem] = useState(null)

  const handleFilterChange = useCallback((patch) => {
    setSearchParams(prev => {
      const current = filtersFromParams(prev)
      const next = { ...current, ...patch }
      if ('topic_ids' in patch && (!patch.topic_ids || patch.topic_ids.length === 0)) {
        next.exclusive = false
      }
      return paramsFromFilters(next)
    }, { replace: true })
  }, [setSearchParams])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    setItems([])
    setPage(1)
    setLoading(true)
    setError(null)

    api.questions.list(
      {
        subject_id: filters.subject_id || undefined,
        stream_id: filters.stream_id || undefined,
        level_id: filters.level_id || undefined,
        school_id: filters.school_id || undefined,
        exam_type_id: filters.exam_type_id || undefined,
        year: filters.year || undefined,
        topic_ids: filters.topic_ids,
        exclusive: filters.exclusive,
        search: filters.search || undefined,
        page: 1,
        page_size: PAGE_SIZE,
      },
      controller.signal,
    )
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  async function loadMore() {
    if (loadingMore) return
    const nextPage = page + 1
    setLoadingMore(true)
    setError(null)
    try {
      const res = await api.questions.list({
        subject_id: filters.subject_id || undefined,
        stream_id: filters.stream_id || undefined,
        level_id: filters.level_id || undefined,
        school_id: filters.school_id || undefined,
        exam_type_id: filters.exam_type_id || undefined,
        year: filters.year || undefined,
        topic_ids: filters.topic_ids,
        exclusive: filters.exclusive,
        search: filters.search || undefined,
        page: nextPage,
        page_size: PAGE_SIZE,
      })
      setItems(prev => {
        const seen = new Set(prev.map(it => it.id))
        const additions = (res.items || []).filter(it => !seen.has(it.id))
        return [...prev, ...additions]
      })
      setTotal(res.total || 0)
      setPage(nextPage)
    } catch (e) {
      setError(e?.message || 'Failed to load more questions')
    } finally {
      setLoadingMore(false)
    }
  }

  const hasMore = items.length < total

  return (
    <div className="min-h-screen bg-white">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <Link to="/" className="text-lg font-semibold text-gray-900">PilloraQuestionBank</Link>
        <div className="flex items-center gap-3 text-sm">
          {user ? (
            <>
              <Link to="/generate" className="text-blue-600 hover:underline">Create Paper</Link>
              <span className="text-gray-500">{user.email}</span>
              {user.role === 'admin' ? (
                <Link to="/admin/reference" className="text-blue-600 hover:underline">Admin</Link>
              ) : null}
            </>
          ) : (
            <Link to="/login" className="text-blue-600 hover:underline">Log in</Link>
          )}
        </div>
      </header>

      <main className="max-w-[90%] mx-auto px-6 py-6 space-y-6">
        <FilterBar filters={filters} onFilterChange={handleFilterChange} />

        <ErrorBanner message={error} />

        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-600">
            {loading
              ? 'Loading…'
              : total === 0
                ? 'No questions match the current filters.'
                : `Showing ${items.length} of ${total} ${total === 1 ? 'question' : 'questions'}`}
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16"><Spinner size="lg" /></div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {items.map(item => (
              <QuestionCard key={item.id} item={item} onClick={() => setSelectedItem(item)} />
            ))}
          </div>
        )}

        {!loading && hasMore ? (
          <div className="flex items-center justify-center pt-2 pb-8">
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="px-6 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {loadingMore ? <Spinner size="sm" /> : null}
              {loadingMore ? 'Loading…' : 'Load more'}
            </button>
          </div>
        ) : null}
      </main>

      {selectedItem ? (
        <QuestionDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} />
      ) : null}
    </div>
  )
}
