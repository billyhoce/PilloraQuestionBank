import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import premiumLocked from '../../assets/premium-locked.svg'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import Spinner from '../Spinner'
import ErrorBanner from '../ErrorBanner'
import TagCombobox from '../TagCombobox'

export default function QuestionDetailModal({ item, onClose, onTagsChanged }) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [questionTags, setQuestionTags] = useState([])
  const [allTags, setAllTags] = useState([])
  const [tagError, setTagError] = useState(null)
  const [savingTags, setSavingTags] = useState(false)

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.questions.get(item.id)
      .then(data => { if (!cancelled) { setDetail(data); setQuestionTags(data.tags || []) } })
      .catch(e => { if (!cancelled) setError(e.message || 'Failed to load question') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [item.id])

  useEffect(() => {
    if (!isAdmin) return
    let cancelled = false
    api.tags.list().then(data => { if (!cancelled) setAllTags(data || []) }).catch(() => {})
    return () => { cancelled = true }
  }, [isAdmin])

  async function persistTags(nextTags) {
    const prev = questionTags
    setQuestionTags(nextTags)  // optimistic
    setSavingTags(true)
    setTagError(null)
    try {
      await api.papers.setQuestionTags(item.id, nextTags.map(t => t.id))
      onTagsChanged?.(item.id, nextTags)
    } catch (e) {
      setQuestionTags(prev)  // revert
      setTagError(e.message || 'Failed to update tags')
    } finally {
      setSavingTags(false)
    }
  }

  function addTag(tag) {
    if (questionTags.some(t => t.id === tag.id)) return
    persistTags([...questionTags, tag])
  }
  function removeTag(id) {
    persistTags(questionTags.filter(t => t.id !== id))
  }

  const { paper_info, question_number } = item
  const title = `${paper_info.school_name} ${paper_info.year} ${paper_info.exam_type_name} ${paper_info.paper_number} · Q${question_number}`
  const subtopicNames = detail
    ? [...new Set(detail.topics.flatMap(t => t.subtopic_names || []))]
    : []

  return (
    <div
      className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center overflow-y-auto p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-3xl my-8"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-start justify-between rounded-t-lg z-10">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
            {subtopicNames.length > 0 ? (
              <ul className="text-xs text-gray-500 mt-1 space-y-0.5">
                {subtopicNames.map(name => <li key={name}>{name}</li>)}
              </ul>
            ) : null}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none ml-4"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="px-6 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12"><Spinner size="lg" /></div>
          ) : error ? (
            <ErrorBanner message={error} />
          ) : detail ? (
            <div className="space-y-6">
              <section>
                <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-2">Tags</h3>
                {questionTags.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {questionTags.map(t => (
                      <span
                        key={t.id}
                        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 border border-amber-300 text-amber-800 rounded-full bg-amber-50"
                      >
                        {t.name}
                        {isAdmin ? (
                          <button
                            type="button"
                            onClick={() => removeTag(t.id)}
                            disabled={savingTags}
                            className="text-amber-500 hover:text-red-600 disabled:opacity-50"
                            aria-label={`Remove ${t.name}`}
                          >×</button>
                        ) : null}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic mb-2">No tags</p>
                )}
                {isAdmin ? (
                  <TagCombobox
                    tags={allTags}
                    selectedIds={questionTags.map(t => t.id)}
                    onAdd={addTag}
                  />
                ) : null}
                {tagError ? <p className="text-xs text-red-600 mt-1">{tagError}</p> : null}
              </section>

              {detail.locked ? (
                <section className="flex flex-col items-center justify-center gap-4 rounded-lg border border-amber-200 bg-gradient-to-br from-amber-50 to-gray-100 py-10 px-6 text-center">
                  <img
                    src={premiumLocked}
                    alt="Premium content — subscribe to unlock"
                    className="w-full max-w-sm rounded border border-amber-200"
                  />
                  <p className="text-xs text-gray-500">Subscribe to view the full question and answer.</p>
                  <Link
                    to="/subscribe"
                    className="text-sm font-medium px-4 py-2 rounded border border-amber-400 text-amber-800 bg-amber-50 hover:bg-amber-100 transition-colors"
                  >
                    Go Premium
                  </Link>
                </section>
              ) : (
                <>
                  <section>
                    {detail.marks != null ? (
                      <div className="text-sm text-gray-600 mb-2">Marks: {detail.marks}</div>
                    ) : null}
                    <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-2">Question</h3>
                    <div className="space-y-2">
                      {detail.question_pages.map(p => (
                        <img key={p.id} src={p.url} alt={`Q page ${p.page_order}`} className="w-full border border-gray-200 rounded" />
                      ))}
                    </div>
                  </section>
                  {detail.answer_pages.length > 0 ? (
                    <section>
                      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-2">Answer</h3>
                      <div className="space-y-2">
                        {detail.answer_pages.map(p => (
                          <img key={p.id} src={p.url} alt={`A page ${p.page_order}`} className="w-full border border-gray-200 rounded" />
                        ))}
                      </div>
                    </section>
                  ) : null}
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
