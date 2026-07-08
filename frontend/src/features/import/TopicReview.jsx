import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../api/client'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'
import TopicCombobox from './TopicCombobox'
import { buildTopicLookup, selectionsToAssignments } from './topicUtils'
import { formatTopic } from '../../utils/topicFormat'

const REQUEST_INTERVAL_MS = 1300

function createRateLimitedQueue(intervalMs) {
  let lastStart = 0
  return (fn) => {
    const now = Date.now()
    const wait = Math.max(0, lastStart + intervalMs - now)
    lastStart = now + wait
    return new Promise((resolve) => setTimeout(resolve, wait)).then(fn)
  }
}


export default function TopicReview({ paperId, questions, subjectId, streamId, onDone, onCancel }) {
  const [topics, setTopics] = useState(null)
  const [topicsError, setTopicsError] = useState(null)
  const [questionState, setQuestionState] = useState(() =>
    Object.fromEntries(questions.map(q => [q.id, { status: 'loading', selected: [], marks: q.marks ?? null, error: null }]))
  )
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [expandedImage, setExpandedImage] = useState(null)

  const lookup = useMemo(() => topics ? buildTopicLookup(topics) : null, [topics])
  const enqueue = useMemo(() => createRateLimitedQueue(REQUEST_INTERVAL_MS), [])
  const abortRef = useRef(null)

  const labelQuestion = useCallback(async (qid) => {
    setQuestionState(prev => ({ ...prev, [qid]: { ...prev[qid], status: 'loading', error: null } }))
    try {
      const result = await enqueue(() => api.import.aiTopicsForQuestion(qid, abortRef.current?.signal))
      setQuestionState(prev => ({
        ...prev,
        [qid]: { status: 'ready', selected: result.selections || [], marks: result.marks ?? null, error: null },
      }))
    } catch (e) {
      if (e.name === 'AbortError') return
      setQuestionState(prev => ({
        ...prev,
        [qid]: { ...prev[qid], status: 'error', error: e.message || 'Labeling failed' },
      }))
    }
  }, [enqueue])

  useEffect(() => {
    api.topics.list(subjectId, streamId)
      .then(setTopics)
      .catch((e) => setTopicsError(e.message || 'Failed to load topics'))
  }, [subjectId, streamId])

  useEffect(() => {
    abortRef.current = new AbortController()
    questions.forEach(q => { labelQuestion(q.id) })
    return () => {
      abortRef.current?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function addTopic(qid, sel) {
    setQuestionState(prev => {
      const cur = prev[qid]
      if (cur.selected.some(s => s.topic_id === sel.topic_id && s.subtopic_id === sel.subtopic_id)) return prev
      return { ...prev, [qid]: { ...cur, selected: [...cur.selected, sel] } }
    })
  }

  function removeTopic(qid, idx) {
    setQuestionState(prev => {
      const cur = prev[qid]
      return { ...prev, [qid]: { ...cur, selected: cur.selected.filter((_, i) => i !== idx) } }
    })
  }

  function setMarks(qid, val) {
    setQuestionState(prev => ({ ...prev, [qid]: { ...prev[qid], marks: val } }))
  }

  const anyLoading = Object.values(questionState).some(s => s.status === 'loading')

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    try {
      const question_topics = questions.map(q => ({
        question_id: q.id,
        marks: questionState[q.id]?.marks ?? null,
        topic_assignments: selectionsToAssignments(questionState[q.id]?.selected ?? []),
      }))
      await api.import.saveTopics(paperId, question_topics)
      onDone()
    } catch (e) {
      setSaveError(e.message || 'Failed to save topics')
    } finally {
      setSaving(false)
    }
  }

  if (topicsError) {
    return (
      <div className="p-6">
        <ErrorBanner message={topicsError} />
      </div>
    )
  }

  if (!topics) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-3">
        <Spinner size="lg" />
        <p className="text-sm text-gray-600">Loading topics…</p>
      </div>
    )
  }

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-900">Review AI topic suggestions</h1>
        <p className="text-xs text-gray-500">
          {anyLoading ? 'Some questions still labeling…' : 'All questions labeled'}
        </p>
      </div>

      <div className="space-y-6">
        {questions.map(q => {
          const state = questionState[q.id] || { status: 'loading', selected: [], error: null }
          const questionPages = (q.pages || []).filter(p => p.page_type === 'question')
          return (
            <div key={q.id} className="border border-gray-200 rounded-lg p-4 bg-white">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-gray-900">Q{q.question_number}</span>
                  <label className="flex items-center gap-1 text-xs text-gray-500">
                    Marks
                    <input
                      type="number"
                      min="0"
                      value={state.marks ?? ''}
                      onChange={(e) => setMarks(q.id, e.target.value !== '' ? Number(e.target.value) : null)}
                      placeholder="—"
                      className="w-16 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  {state.status === 'loading' && (
                    <span className="flex items-center gap-1 text-xs text-gray-500">
                      <Spinner size="sm" /> Labeling…
                    </span>
                  )}
                  {state.status === 'ready' && (
                    <span className="text-xs text-green-700">Suggested</span>
                  )}
                  {state.status === 'error' && (
                    <span className="text-xs text-red-600">{state.error}</span>
                  )}
                  <button
                    type="button"
                    onClick={() => labelQuestion(q.id)}
                    disabled={state.status === 'loading'}
                    className="text-xs px-2 py-1 rounded border border-gray-300 hover:border-blue-400 disabled:opacity-50"
                  >
                    {state.status === 'error' ? 'Retry' : 'Re-run AI'}
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex flex-col gap-2 max-h-screen overflow-y-auto bg-gray-50 rounded p-2">
                  {questionPages.length === 0 && (
                    <p className="text-xs text-gray-500">No question images</p>
                  )}
                  {questionPages.map((p, i) => (
                    <img
                      key={i}
                      src={p.url}
                      alt={`Q${q.question_number} page ${i + 1}`}
                      className="w-full h-auto border border-gray-200 rounded cursor-pointer hover:opacity-80 transition-opacity"
                      onClick={() => setExpandedImage(p.url)}
                    />
                  ))}
                </div>

                <div className="flex flex-col gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Topics</p>
                    {state.selected.length === 0 && state.status !== 'loading' && (
                      <p className="text-sm text-gray-400 italic">No topics selected</p>
                    )}
                    {state.selected.map((sel, i) => {
                      let label
                      if (sel.subtopic_id != null) {
                        const s = lookup.subtopicById.get(sel.subtopic_id)
                        label = s ? <><strong>{formatTopic(s.topic_number, s.topic_name)}</strong> » {s.name}</> : `Unknown subtopic ${sel.subtopic_id}`
                      } else {
                        const t = lookup.topicById.get(sel.topic_id)
                        label = t ? <strong>{formatTopic(t.topic_number, t.name)}</strong> : `Unknown topic ${sel.topic_id}`
                      }
                      return (
                        <div key={i} className="flex items-start gap-2 mb-2 bg-blue-50 border border-blue-200 rounded-lg p-2">
                          <p className="text-sm text-gray-700 flex-grow">{label}</p>
                          <button
                            type="button"
                            onClick={() => removeTopic(q.id, i)}
                            className="text-gray-400 hover:text-red-600 text-lg flex-shrink-0 mt-0.5"
                            aria-label="Remove"
                          >
                            ×
                          </button>
                        </div>
                      )
                    })}
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Add topic</p>
                    <TopicCombobox
                      topics={topics}
                      selected={state.selected}
                      onAdd={(sel) => addTopic(q.id, sel)}
                    />
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {saveError && (
        <div className="mt-4">
          <ErrorBanner message={saveError} />
        </div>
      )}

      {expandedImage && (
        <div
          className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
          onClick={() => setExpandedImage(null)}
        >
          <div className="max-w-4xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <img
              src={expandedImage}
              alt="Expanded"
              className="w-full h-auto"
            />
          </div>
          <button
            className="fixed top-4 right-4 text-white text-2xl bg-black bg-opacity-50 hover:bg-opacity-75 rounded-full w-10 h-10 flex items-center justify-center transition-all"
            onClick={() => setExpandedImage(null)}
          >
            ×
          </button>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between sticky bottom-0 bg-white py-3 border-t border-gray-200">
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="text-sm px-4 py-2 rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Cancel import
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || anyLoading}
          className="bg-blue-600 hover:bg-blue-700 text-white rounded px-6 py-2 text-sm font-medium disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Confirm & Save Topics'}
        </button>
      </div>
    </div>
  )
}
