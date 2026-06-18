import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'
import useRefs from './useRefs'
import PaperMetadataBar from './PaperMetadataBar'
import QuestionEditor from './QuestionEditor'

const AI_INTERVAL_MS = 1300

function buildLookup(topics) {
  const m = new Map()
  for (const t of topics || []) {
    for (const s of t.subtopics || []) m.set(s.id, { name: s.name, topic_name: t.name })
  }
  return m
}

function rateLimited(intervalMs) {
  let last = 0
  return (fn) => {
    const now = Date.now()
    const wait = Math.max(0, last + intervalMs - now)
    last = now + wait
    return new Promise((r) => setTimeout(r, wait)).then(fn)
  }
}

export default function PaperEditor() {
  const { id } = useParams()
  const refs = useRefs()

  const [paper, setPaper] = useState(null)
  const [metadata, setMetadata] = useState(null)
  const [questions, setQuestions] = useState([])
  const [topics, setTopics] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)

  const [newDrafts, setNewDrafts] = useState([])
  const [aiSeed, setAiSeed] = useState({})
  const [relabelVersion, setRelabelVersion] = useState(0)
  const [relabelStatus, setRelabelStatus] = useState(null)
  const [expandedImage, setExpandedImage] = useState(null)

  const editorRefs = useRef(new Map())
  const [savingAll, setSavingAll] = useState(false)
  const [saveAllError, setSaveAllError] = useState(null)
  const [saveAllOk, setSaveAllOk] = useState(false)

  function setEditorRef(key) {
    return (el) => {
      if (el) editorRefs.current.set(key, el)
      else editorRefs.current.delete(key)
    }
  }

  const lookup = useMemo(() => buildLookup(topics), [topics])
  const enqueue = useRef(rateLimited(AI_INTERVAL_MS)).current

  const loadTopics = useCallback((subjectId, streamId) => {
    return api.topics.list(subjectId, streamId).then(setTopics).catch(() => setTopics([]))
  }, [])

  useEffect(() => {
    setLoading(true)
    api.papers.get(id)
      .then((p) => {
        setPaper(p)
        setQuestions(p.questions)
        setMetadata({
          subject_id: p.subject_id,
          stream_id: p.stream_id,
          level_id: p.level_id,
          school_id: p.school_id,
          exam_type_id: p.exam_type_id,
          year: String(p.year),
          paper_number: p.paper_number,
        })
        return loadTopics(p.subject_id, p.stream_id)
      })
      .catch((e) => setLoadError(e.message))
      .finally(() => setLoading(false))
  }, [id, loadTopics])

  async function handleSaveMetadata(draft, changed) {
    await api.papers.update(id, {
      subject_id: draft.subject_id,
      stream_id: draft.stream_id,
      level_id: draft.level_id,
      school_id: draft.school_id,
      exam_type_id: draft.exam_type_id,
      year: Number(draft.year),
      paper_number: draft.paper_number,
    })
    setMetadata({ ...draft, year: String(draft.year) })

    if (changed) {
      setRelabelStatus('running')
      const fresh = await api.papers.get(id)
      setQuestions(fresh.questions)
      await loadTopics(draft.subject_id, draft.stream_id)
      const seed = {}
      for (const q of fresh.questions) {
        try {
          const res = await enqueue(() => api.import.aiTopicsForQuestion(q.id))
          seed[q.id] = res.suggestions || []
        } catch {
          seed[q.id] = []
        }
      }
      setAiSeed(seed)
      setRelabelVersion((v) => v + 1)
      setRelabelStatus('done')
    }
  }

  function handleQuestionSaved(updated) {
    setQuestions((prev) => prev.map((q) => (q.id === updated.id ? updated : q)))
    setAiSeed((prev) => {
      if (!(updated.id in prev)) return prev
      const next = { ...prev }
      delete next[updated.id]
      return next
    })
  }

  function handleQuestionDeleted(qid) {
    setQuestions((prev) => prev.filter((q) => q.id !== qid))
  }

  function handleAddDraft() {
    const maxNum = questions.reduce((m, q) => Math.max(m, q.question_number), 0)
    setNewDrafts((prev) => [
      ...prev,
      { tempId: `d-${Date.now()}-${prev.length}`, question_number: maxNum + 1 + prev.length, marks: null, pages: [], topics: [] },
    ])
  }

  function handleDraftSaved(tempId, serialized) {
    setNewDrafts((prev) => prev.filter((d) => d.tempId !== tempId))
    setQuestions((prev) => [...prev, serialized])
  }

  function handleDraftCancel(tempId) {
    setNewDrafts((prev) => prev.filter((d) => d.tempId !== tempId))
  }

  async function handleSaveAll() {
    const orderedKeys = [
      ...[...questions].sort((a, b) => a.question_number - b.question_number).map((q) => `q-${q.id}`),
      ...newDrafts.map((d) => `draft-${d.tempId}`),
    ]
    const handles = orderedKeys.map((k) => editorRefs.current.get(k)).filter(Boolean)
    if (handles.length === 0) return

    setSavingAll(true)
    setSaveAllError(null)
    setSaveAllOk(false)
    let failures = 0
    for (const h of handles) {
      // Saved sequentially so the server's per-paper uniqueness check sees a
      // consistent state and failures map cleanly to individual editors.
      const ok = await h.save()
      if (!ok) failures += 1
    }
    setSavingAll(false)
    if (failures > 0) {
      setSaveAllError(`${failures} question${failures > 1 ? 's' : ''} couldn't be saved — see the highlighted errors.`)
    } else {
      setSaveAllOk(true)
      setTimeout(() => setSaveAllOk(false), 3000)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-16"><Spinner size="lg" /></div>
  }
  if (loadError) {
    return <div className="max-w-5xl mx-auto"><ErrorBanner message={loadError} /></div>
  }

  const sortedQuestions = [...questions].sort((a, b) => a.question_number - b.question_number)
  const allNumbers = questions.map((q) => q.question_number)

  function scrollToEl(elId) {
    document.getElementById(elId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-900">
          Edit paper
          {paper?.paper_info && (
            <span className="text-sm font-normal text-gray-500 ml-2">
              {paper.paper_info.subject_name} · {paper.paper_info.stream_name} · {paper.paper_info.year} · {paper.paper_info.exam_type_name} Paper {paper.paper_info.paper_number}
            </span>
          )}
        </h1>
        <Link to="/admin/papers" className="text-sm text-blue-600 hover:underline">← Back to papers</Link>
      </div>

      <PaperMetadataBar metadata={metadata} refs={refs} onSave={handleSaveMetadata} />

      {relabelStatus === 'running' && (
        <div className="mb-4 flex items-center gap-2 text-sm text-gray-600">
          <Spinner size="sm" /> Clearing topics and running AI labelling…
        </div>
      )}
      {relabelStatus === 'done' && (
        <div className="mb-4 text-sm text-green-700">
          AI suggested fresh topics. Review each question and Save to persist.
        </div>
      )}

      <div className="flex gap-6 items-start">
        <nav className="hidden md:block flex-shrink-0 sticky top-4 self-start max-h-[calc(100vh-2rem)] overflow-y-auto">
          <p className="text-xs uppercase tracking-wide text-gray-500 mb-2">Questions</p>
          <div className="flex flex-wrap gap-1.5 w-24">
            {sortedQuestions.map((q) => (
              <button
                key={q.id}
                type="button"
                onClick={() => scrollToEl(`q-${q.id}`)}
                title={`Go to question ${q.question_number}`}
                className="w-9 h-9 rounded border border-gray-300 text-sm text-gray-700 hover:border-blue-400 hover:text-blue-600 bg-white"
              >
                {q.question_number}
              </button>
            ))}
            {newDrafts.map((d) => (
              <button
                key={d.tempId}
                type="button"
                onClick={() => scrollToEl(`draft-${d.tempId}`)}
                title="Go to new question"
                className="w-9 h-9 rounded border border-dashed border-gray-400 text-sm text-gray-500 hover:border-blue-400 hover:text-blue-600 bg-white"
              >
                +
              </button>
            ))}
          </div>
        </nav>

        <div className="flex-1 min-w-0">
          <div className="space-y-6">
            {sortedQuestions.map((q) => {
              const seedQuestion = aiSeed[q.id]
                ? { ...q, topics: aiSeed[q.id].map((s) => ({ subtopic_id: s.subtopic_id })) }
                : q
              return (
                <div key={`${q.id}-${relabelVersion}`} id={`q-${q.id}`} className="scroll-mt-4">
                  <QuestionEditor
                    ref={setEditorRef(`q-${q.id}`)}
                    paperId={id}
                    question={seedQuestion}
                    topics={topics}
                    lookup={lookup}
                    usedNumbers={questions.filter((o) => o.id !== q.id).map((o) => o.question_number)}
                    onSaved={handleQuestionSaved}
                    onDeleted={handleQuestionDeleted}
                    onExpand={setExpandedImage}
                  />
                </div>
              )
            })}

            {newDrafts.map((d) => (
              <div key={d.tempId} id={`draft-${d.tempId}`} className="scroll-mt-4">
                <QuestionEditor
                  ref={setEditorRef(`draft-${d.tempId}`)}
                  paperId={id}
                  isNew
                  question={d}
                  topics={topics}
                  lookup={lookup}
                  usedNumbers={allNumbers}
                  onSaved={(serialized) => handleDraftSaved(d.tempId, serialized)}
                  onCancelNew={() => handleDraftCancel(d.tempId)}
                  onExpand={setExpandedImage}
                />
              </div>
            ))}
          </div>

          <div className="mt-6">
            <button
              type="button"
              onClick={handleAddDraft}
              className="text-sm px-4 py-2 rounded border border-dashed border-gray-400 text-gray-700 hover:border-blue-400 hover:text-blue-600 w-full"
            >
              + Add question
            </button>
          </div>
        </div>
      </div>

      {(questions.length > 0 || newDrafts.length > 0) && (
        <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2">
          {saveAllError && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded px-3 py-2 text-xs max-w-xs shadow">
              {saveAllError}
            </div>
          )}
          {saveAllOk && (
            <div className="bg-green-50 border border-green-200 text-green-700 rounded px-3 py-2 text-xs shadow">
              All changes saved
            </div>
          )}
          <button
            type="button"
            onClick={handleSaveAll}
            disabled={savingAll}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-full shadow-lg px-6 py-3 text-sm font-medium flex items-center gap-2"
          >
            {savingAll && <Spinner size="sm" />} Save all
          </button>
        </div>
      )}

      {expandedImage && (
        <div
          className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
          onClick={() => setExpandedImage(null)}
        >
          <div className="max-w-4xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <img src={expandedImage} alt="Expanded" className="w-full h-auto" />
          </div>
          <button
            className="fixed top-4 right-4 text-white text-2xl bg-black bg-opacity-50 hover:bg-opacity-75 rounded-full w-10 h-10 flex items-center justify-center"
            onClick={() => setExpandedImage(null)}
          >×</button>
        </div>
      )}
    </div>
  )
}
