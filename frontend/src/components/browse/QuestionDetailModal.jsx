import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import Spinner from '../Spinner'
import ErrorBanner from '../ErrorBanner'

export default function QuestionDetailModal({ item, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

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
      .then(data => { if (!cancelled) setDetail(data) })
      .catch(e => { if (!cancelled) setError(e.message || 'Failed to load question') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [item.id])

  const { paper_info, question_number } = item
  const title = `${paper_info.school_name} ${paper_info.year} ${paper_info.exam_type_name} ${paper_info.paper_number} · Q${question_number}`
  const subtopicNames = detail
    ? [...new Set(detail.topics.map(t => t.subtopic_name))]
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
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
