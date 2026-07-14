import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import FilterBar from '../components/browse/FilterBar'
import QuestionCard from '../components/browse/QuestionCard'
import QuestionDetailModal from '../components/browse/QuestionDetailModal'
import CoverBodyEditor from '../components/generate/CoverBodyEditor'
import InfoTooltip from '../components/InfoTooltip'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'
import { buildPdfFilename } from '../utils/pdfFilename'

const PAGE_SIZE = 50

const EMPTY_FILTERS = {
  level_id: '',
  stream_id: '',
  subject_id: '',
  school_id: '',
  exam_type_id: '',
  year: '',
  paper_number: '',
  topic_ids: [],
  exclusive: false,
  search: '',
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
    paper_number: filters.paper_number || undefined,
    topic_ids: filters.topic_ids,
    exclusive: filters.exclusive,
    search: filters.search || undefined,
    page,
    page_size: PAGE_SIZE,
  }
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
    paper_number: filters.paper_number || null,
    topic_ids: filters.topic_ids || [],
    exclusive: !!filters.exclusive,
    search: filters.search || null,
  }
}

export default function GeneratePage() {

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
  const [pickingAlgorithm, setPickingAlgorithm] = useState('in-order') // 'random' | 'in-order'
  const [autoLoading, setAutoLoading] = useState(false)
  const [notice, setNotice] = useState(null) // { type: 'warning' | 'success', text }

  // PDF generation state
  const [headerText, setHeaderText] = useState('')
  const [outputMode, setOutputMode] = useState('combined') // 'combined' | 'separate'

  // Cover page state (editable defaults). Title and body start as null =
  // "defaults not loaded yet": the fields are pre-filled from
  // GET /api/generate/cover-defaults (the single source of truth), and any
  // field still null at generate time is omitted from the request so the
  // backend default applies. coverBody holds rich-text HTML (paragraphs plus
  // bold/italic/underline/link), edited via CoverBodyEditor.
  const [includeCover, setIncludeCover] = useState(true)
  const [coverTitle, setCoverTitle] = useState(null)
  const [coverSubtitle1, setCoverSubtitle1] = useState('')
  const [coverSubtitle2, setCoverSubtitle2] = useState('')
  const [coverBody, setCoverBody] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [genProgress, setGenProgress] = useState(0)
  const progressTimer = useRef(null)

  // Pre-fill the cover title/body from the backend defaults. If the user has
  // already typed into a field (no longer null), leave their text alone; if
  // the fetch fails, the fields stay null and the backend defaults apply.
  useEffect(() => {
    const controller = new AbortController()
    api.generate.coverDefaults(controller.signal)
      .then(res => {
        setCoverTitle(prev => prev ?? res.cover_title)
        setCoverBody(prev => prev ?? res.cover_body)
      })
      .catch(() => {})
    return () => controller.abort()
  }, [])

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
        algorithm: pickingAlgorithm,
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

    const ids = cart.map(it => it.id)
    // Cover fields shared by every variant (the answer PDF's cover reads "Answers").
    // Title/body still null (defaults never loaded) are omitted so the backend
    // defaults apply server-side.
    const cover = {
      include_cover: includeCover,
      cover_subtitle1: coverSubtitle1,
      cover_subtitle2: coverSubtitle2,
    }
    if (coverTitle !== null) cover.cover_title = coverTitle
    if (coverBody !== null) cover.cover_body = coverBody
    try {
      if (outputMode === 'combined') {
        const blob = await api.generate.paper({
          question_ids: ids, variant: 'combined', header_text: headerText, ...cover,
        })
        stopProgress()
        setGenProgress(100)
        downloadBlob(blob, buildPdfFilename({ variant: 'combined', title: coverTitle }))
        setNotice({ type: 'success', text: 'Generated combined PDF.' })
      } else {
        const [questionBlob, answerBlob] = await Promise.all([
          api.generate.paper({ question_ids: ids, variant: 'question', header_text: headerText, ...cover }),
          api.generate.paper({ question_ids: ids, variant: 'answer', header_text: '', ...cover }),
        ])
        stopProgress()
        setGenProgress(100)
        downloadBlob(questionBlob, buildPdfFilename({ variant: 'question', title: coverTitle }))
        // Small gap so the browser doesn't drop the second programmatic download.
        setTimeout(
          () => downloadBlob(answerBlob, buildPdfFilename({ variant: 'answer', title: coverTitle })),
          600,
        )
        setNotice({ type: 'success', text: 'Generated question and answer PDFs.' })
      }
    } catch (e) {
      stopProgress()
      setNotice({ type: 'warning', text: e?.message || 'PDF generation failed.' })
    } finally {
      setTimeout(() => { setGenerating(false); setGenProgress(0) }, 800)
    }
  }

  const hasMore = items.length < total

  return (
    <div className="max-w-[90%] mx-auto space-y-6">
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
          <aside className="lg:sticky lg:top-6 lg:self-start lg:h-[calc(100vh-3rem)] lg:overflow-y-auto space-y-4 pr-1">
            {/* Autocreate panel */}
            <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">Autocreate Paper</h2>
              <p className="text-xs text-gray-500">
                Auto-pick a set of questions from the current filters, summing near your target marks.
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
              <div className="space-y-1">
                <div className="flex items-center gap-1 text-xs font-medium text-gray-700">
                  Picking Algorithm
                  <InfoTooltip label="What does Picking Algorithm do?">
                    <strong>In-order</strong> deterministically picks from the top of the filtered
                    list, so the same filters always give the same questions.{' '}
                    <strong>Random</strong> picks a different fitting set each time you autocreate.
                  </InfoTooltip>
                </div>
                <div className="flex gap-3 text-xs text-gray-700">
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name="picking-algorithm"
                      checked={pickingAlgorithm === 'in-order'}
                      onChange={() => setPickingAlgorithm('in-order')}
                    />
                    In-order
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name="picking-algorithm"
                      checked={pickingAlgorithm === 'random'}
                      onChange={() => setPickingAlgorithm('random')}
                    />
                    Random
                  </label>
                </div>
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
                <ul className="space-y-2">
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

              <div className="space-y-2 pt-1 border-t border-gray-100">
                <label className="flex items-center gap-2 text-xs font-medium text-gray-700 pt-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={includeCover}
                    onChange={e => setIncludeCover(e.target.checked)}
                  />
                  Include cover page
                </label>
                {includeCover ? (
                  <div className="space-y-2">
                    <input
                      type="text"
                      value={coverTitle ?? ''}
                      onChange={e => setCoverTitle(e.target.value)}
                      placeholder="Title"
                      className="w-full px-2 py-1 border border-gray-300 rounded text-xs"
                    />
                    <input
                      type="text"
                      value={coverSubtitle1}
                      onChange={e => setCoverSubtitle1(e.target.value)}
                      placeholder="Subtitle 1 — e.g. Secondary 3 Mathematics"
                      className="w-full px-2 py-1 border border-gray-300 rounded text-xs"
                    />
                    <input
                      type="text"
                      value={coverSubtitle2}
                      onChange={e => setCoverSubtitle2(e.target.value)}
                      placeholder="Subtitle 2 — e.g. 2024 Prelim"
                      className="w-full px-2 py-1 border border-gray-300 rounded text-xs"
                    />
                    <CoverBodyEditor value={coverBody} onChange={setCoverBody} />
                    <p className="text-[11px] text-gray-400">
                      Marks box on the cover shows the paper total automatically.
                    </p>
                  </div>
                ) : null}
              </div>

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

              <div className="space-y-1 pt-1">
                <span className="text-xs text-gray-600">Download as</span>
                <div className="flex flex-col gap-1 text-xs text-gray-700">
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name="output-mode"
                      checked={outputMode === 'combined'}
                      onChange={() => setOutputMode('combined')}
                    />
                    1 combined PDF (answers after questions)
                  </label>
                  <label className="flex items-center gap-1 cursor-pointer">
                    <input
                      type="radio"
                      name="output-mode"
                      checked={outputMode === 'separate'}
                      onChange={() => setOutputMode('separate')}
                    />
                    Separate question &amp; answer PDFs
                  </label>
                </div>
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

      {selectedItem ? (
        <QuestionDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} />
      ) : null}
    </div>
  )
}
