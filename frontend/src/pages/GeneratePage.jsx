import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'
import FilterBar from '../components/browse/FilterBar'
import QuestionCard from '../components/browse/QuestionCard'
import QuestionDetailModal from '../components/browse/QuestionDetailModal'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'

const PAGE_SIZE = 50

const EMPTY_FILTERS = {
  level_id: '',
  stream_id: '',
  subject_id: '',
  school_id: '',
  exam_type_id: '',
  year: '',
  topic_ids: [],
  exclusive: false,
  subtopic_keyword: '',
}

// Map the UI filter object to api.questions.list arguments (same as BrowsePage).
function filtersToListArgs(filters, page) {
  return {
    subject_id: filters.subject_id || undefined,
    stream_id: filters.stream_id || undefined,
    level_id: filters.level_id || undefined,
    school_id: filters.school_id || undefined,
    exam_type_id: filters.exam_type_id || undefined,
    year: filters.year || undefined,
    topic_ids: filters.topic_ids,
    exclusive: filters.exclusive,
    subtopic_keyword: filters.subtopic_keyword || undefined,
    page,
    page_size: PAGE_SIZE,
  }
}

// Timestamp for download filenames, e.g. "2026-07-04_16-45-30".
function formatTimestamp(d) {
  const p = (n) => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
    `_${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}`
  )
}

// Trigger a browser download of a Blob under the given filename.
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  // Revoke on the next tick so the download has started.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// Map the UI filter object to the /generate/select `filters` payload (ints/null).
function filtersToSelectPayload(filters) {
  const num = (v) => (v === '' || v == null ? null : Number(v))
  return {
    subject_id: num(filters.subject_id),
    stream_id: num(filters.stream_id),
    level_id: num(filters.level_id),
    school_id: num(filters.school_id),
    exam_type_id: num(filters.exam_type_id),
    year: num(filters.year),
    topic_ids: filters.topic_ids || [],
    exclusive: !!filters.exclusive,
    subtopic_keyword: filters.subtopic_keyword || null,
  }
}

export default function GeneratePage() {
  const { user } = useAuth()

  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [selectedItem, setSelectedItem] = useState(null)

  // Selection cart — full list-item objects, de-duped by id.
  const [cart, setCart] = useState([])

  // Autocreate panel state
  const [targetMarks, setTargetMarks] = useState('')
  const [autoMode, setAutoMode] = useState('replace') // 'replace' | 'add'
  const [autoLoading, setAutoLoading] = useState(false)
  const [notice, setNotice] = useState(null) // { type: 'warning' | 'success', text }

  // PDF generation state
  const [headerText, setHeaderText] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genProgress, setGenProgress] = useState(0)
  const progressTimer = useRef(null)

  const handleFilterChange = useCallback((patch) => {
    setFilters(prev => {
      const next = { ...prev, ...patch }
      if ('topic_ids' in patch && (!patch.topic_ids || patch.topic_ids.length === 0)) {
        next.exclusive = false
      }
      return next
    })
  }, [])

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  async function loadMore() {
    if (loadingMore) return
    const nextPage = page + 1
    setLoadingMore(true)
    setError(null)
    try {
      const res = await api.questions.list(filtersToListArgs(filters, nextPage))
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

  const cartIds = useMemo(() => new Set(cart.map(it => it.id)), [cart])
  const cartTotalMarks = useMemo(
    () => cart.reduce((sum, it) => sum + (it.marks || 0), 0),
    [cart],
  )
  const hasUnmarked = cart.some(it => it.marks == null)

  function toggleSelect(item) {
    setCart(prev => (
      prev.some(it => it.id === item.id)
        ? prev.filter(it => it.id !== item.id)
        : [...prev, item]
    ))
  }

  function removeFromCart(id) {
    setCart(prev => prev.filter(it => it.id !== id))
  }

  function mergeIntoCart(newItems) {
    setCart(prev => {
      const seen = new Set(prev.map(it => it.id))
      return [...prev, ...newItems.filter(it => !seen.has(it.id))]
    })
  }

  async function handleAutocreate() {
    setNotice(null)
    const target = Number(targetMarks)
    if (!Number.isFinite(target) || target <= 0) {
      setNotice({ type: 'warning', text: 'Enter a target mark total greater than 0.' })
      return
    }

    let requestTarget = target
    let excludeIds = []
    if (autoMode === 'add') {
      requestTarget = target - cartTotalMarks
      excludeIds = cart.map(it => it.id)
      if (requestTarget <= 0) {
        setNotice({ type: 'warning', text: `Your selection already totals ${cartTotalMarks} marks, at or above the target.` })
        return
      }
    }

    setAutoLoading(true)
    try {
      const res = await api.generate.select({
        filters: filtersToSelectPayload(filters),
        target_marks: requestTarget,
        exclude_question_ids: excludeIds,
      })
      const newItems = res.items || []
      if (autoMode === 'replace') {
        setCart(newItems)
      } else {
        mergeIntoCart(newItems)
      }
      if (res.warning) {
        setNotice({ type: 'warning', text: res.warning })
      } else if (newItems.length === 0) {
        setNotice({ type: 'warning', text: 'No questions were selected.' })
      } else {
        const finalTotal = autoMode === 'replace' ? res.total_marks : cartTotalMarks + res.total_marks
        setNotice({ type: 'success', text: `Selected ${newItems.length} questions (${finalTotal} marks).` })
      }
    } catch (e) {
      setNotice({ type: 'warning', text: e?.message || 'Autocreate failed.' })
    } finally {
      setAutoLoading(false)
    }
  }

  function stopProgress() {
    if (progressTimer.current) {
      clearInterval(progressTimer.current)
      progressTimer.current = null
    }
  }

  useEffect(() => stopProgress, [])

  async function handleGenerate() {
    if (cart.length === 0 || generating) return
    setNotice(null)
    setGenerating(true)
    setGenProgress(0)

    // Estimated bar: ease toward ~90% while the server works; completion snaps to 100%.
    stopProgress()
    progressTimer.current = setInterval(() => {
      setGenProgress(p => (p < 90 ? p + Math.max(1, (90 - p) * 0.08) : p))
    }, 200)

    const ts = formatTimestamp(new Date())
    const ids = cart.map(it => it.id)
    try {
      const [questionBlob, answerBlob] = await Promise.all([
        api.generate.paper({ question_ids: ids, variant: 'question', header_text: headerText }),
        api.generate.paper({ question_ids: ids, variant: 'answer', header_text: '' }),
      ])
      stopProgress()
      setGenProgress(100)
      downloadBlob(questionBlob, `${ts}_question.pdf`)
      // Small gap so the browser doesn't drop the second programmatic download.
      setTimeout(() => downloadBlob(answerBlob, `${ts}_answer.pdf`), 600)
      setNotice({ type: 'success', text: 'Generated question and answer PDFs.' })
    } catch (e) {
      stopProgress()
      setNotice({ type: 'warning', text: e?.message || 'PDF generation failed.' })
    } finally {
      setTimeout(() => { setGenerating(false); setGenProgress(0) }, 800)
    }
  }

  const hasMore = items.length < total

  return (
    <div className="min-h-screen bg-white">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-lg font-semibold text-gray-900">PilloraQuestionBank</Link>
          <span className="text-sm text-gray-400">/</span>
          <span className="text-sm font-medium text-gray-700">Create Paper</span>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <Link to="/" className="text-blue-600 hover:underline">Browse</Link>
          {user ? <span className="text-gray-500">{user.email}</span> : null}
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-6">
        <FilterBar filters={filters} onFilterChange={handleFilterChange} />

        <ErrorBanner message={error} />

        <div className="lg:grid lg:grid-cols-[1fr_360px] lg:gap-6 space-y-6 lg:space-y-0">
          {/* Results */}
          <section className="space-y-4">
            <div className="text-sm text-gray-600">
              {loading
                ? 'Loading…'
                : total === 0
                  ? 'No questions match the current filters.'
                  : `Showing ${items.length} of ${total} ${total === 1 ? 'question' : 'questions'}`}
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-16"><Spinner size="lg" /></div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
                {items.map(item => (
                  <QuestionCard
                    key={item.id}
                    item={item}
                    selectable
                    selected={cartIds.has(item.id)}
                    onClick={() => setSelectedItem(item)}
                    onToggleSelect={() => toggleSelect(item)}
                  />
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
          </section>

          {/* Selection cart + autocreate */}
          <aside className="lg:sticky lg:top-6 lg:self-start space-y-4">
            {/* Autocreate panel */}
            <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">Autocreate Paper</h2>
              <p className="text-xs text-gray-500">
                Auto-pick a randomized set of questions from the current filters, summing near your target marks.
              </p>
              <div className="flex items-center gap-2">
                <label className="text-xs text-gray-600" htmlFor="target-marks">Target marks</label>
                <input
                  id="target-marks"
                  type="number"
                  min="1"
                  value={targetMarks}
                  onChange={e => setTargetMarks(e.target.value)}
                  className="w-24 px-2 py-1 border border-gray-300 rounded text-sm"
                  placeholder="e.g. 50"
                />
              </div>
              <div className="flex gap-3 text-xs text-gray-700">
                <label className="flex items-center gap-1 cursor-pointer">
                  <input
                    type="radio"
                    name="auto-mode"
                    checked={autoMode === 'replace'}
                    onChange={() => setAutoMode('replace')}
                  />
                  Replace selection
                </label>
                <label className="flex items-center gap-1 cursor-pointer">
                  <input
                    type="radio"
                    name="auto-mode"
                    checked={autoMode === 'add'}
                    onChange={() => setAutoMode('add')}
                  />
                  Add to selection
                </label>
              </div>
              <button
                type="button"
                onClick={handleAutocreate}
                disabled={autoLoading}
                className="w-full px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {autoLoading ? <Spinner size="sm" /> : null}
                {autoLoading ? 'Selecting…' : 'Autocreate Paper'}
              </button>
              {notice ? (
                <div
                  className={`text-xs rounded px-2 py-1.5 ${
                    notice.type === 'success'
                      ? 'bg-green-50 text-green-700 border border-green-200'
                      : 'bg-amber-50 text-amber-800 border border-amber-200'
                  }`}
                >
                  {notice.text}
                </div>
              ) : null}
            </div>

            {/* Selection cart */}
            <div className="border border-gray-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-900">
                  Selection ({cart.length})
                </h2>
                {cart.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => setCart([])}
                    className="text-xs text-gray-500 hover:text-red-600"
                  >
                    Clear
                  </button>
                ) : null}
              </div>

              <div className="text-sm text-gray-700">
                Total: <span className="font-semibold">{cartTotalMarks} marks</span>
                {hasUnmarked ? (
                  <span className="block text-xs text-amber-700 mt-0.5">Some questions have no marks set.</span>
                ) : null}
              </div>

              {cart.length === 0 ? (
                <p className="text-xs text-gray-400">
                  Add questions from the list, or use Autocreate above.
                </p>
              ) : (
                <ul className="space-y-2 max-h-[50vh] overflow-y-auto">
                  {cart.map(it => (
                    <li key={it.id} className="flex items-start justify-between gap-2 text-xs border-b border-gray-100 pb-2">
                      <div className="min-w-0">
                        <div className="font-medium text-gray-800 truncate">
                          {it.paper_info.school_name} {it.paper_info.year} · Q{it.question_number}
                        </div>
                        <div className="text-gray-500">
                          {it.marks != null ? `${it.marks} ${it.marks === 1 ? 'mark' : 'marks'}` : 'No marks'}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeFromCart(it.id)}
                        className="text-gray-400 hover:text-red-600 shrink-0"
                        aria-label="Remove"
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <div className="space-y-1 pt-1">
                <label className="text-xs text-gray-600" htmlFor="header-text">
                  Header / instructions (optional)
                </label>
                <textarea
                  id="header-text"
                  rows={2}
                  value={headerText}
                  onChange={e => setHeaderText(e.target.value)}
                  placeholder="e.g. Answer all questions. Time: 2 hours."
                  className="w-full px-2 py-1 border border-gray-300 rounded text-xs resize-y"
                />
              </div>

              {generating ? (
                <div className="space-y-1">
                  <div className="h-2 w-full bg-gray-200 rounded overflow-hidden">
                    <div
                      className="h-full bg-blue-600 transition-all duration-200"
                      style={{ width: `${Math.round(genProgress)}%` }}
                    />
                  </div>
                  <div className="text-xs text-gray-500">Generating PDFs… {Math.round(genProgress)}%</div>
                </div>
              ) : null}

              <button
                type="button"
                onClick={handleGenerate}
                disabled={cart.length === 0 || generating}
                className="w-full px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {generating ? <Spinner size="sm" /> : null}
                {generating ? 'Generating…' : 'Generate PDF'}
              </button>
            </div>
          </aside>
        </div>
      </main>

      {selectedItem ? (
        <QuestionDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} />
      ) : null}
    </div>
  )
}
