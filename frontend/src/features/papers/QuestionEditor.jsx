import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import { api } from '../../api/client'
import Spinner from '../../components/Spinner'
import ConfirmDialog from '../../components/ConfirmDialog'
import TopicCombobox from '../import/TopicCombobox'
import PageImageEditor, { existingPageDraft } from './PageImageEditor'
import { selectionsToAssignments } from '../import/topicUtils'
import { formatTopic } from '../../utils/topicFormat'

function seedPages(question, type) {
  return (question.pages || [])
    .filter((p) => p.page_type === type)
    .sort((a, b) => a.page_order - b.page_order)
    .map(existingPageDraft)
}

function QuestionEditor({
  paperId, question, isNew = false, topics, lookup, usedNumbers = [], onSaved, onCancelNew, onDeleted, onExpand,
}, ref) {
  const [questionNumber, setQuestionNumber] = useState(String(question.question_number ?? ''))
  const [marks, setMarks] = useState(question.marks != null ? String(question.marks) : '')
  const [qPages, setQPages] = useState(() => (isNew ? [] : seedPages(question, 'question')))
  const [aPages, setAPages] = useState(() => (isNew ? [] : seedPages(question, 'answer')))
  const [selected, setSelected] = useState(() => question.selections || [])

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const { subtopicById, topicById } = lookup || {}

  function addTopic(sel) {
    setSelected((prev) =>
      prev.some((s) => s.topic_id === sel.topic_id && s.subtopic_id === sel.subtopic_id) ? prev : [...prev, sel]
    )
  }
  function removeTopic(idx) {
    setSelected((prev) => prev.filter((_, i) => i !== idx))
  }

  function buildPayload() {
    const ordered = [...qPages, ...aPages].map((p, idx) => ({
      id: p.id,
      temp_key: p.temp_key,
      page_type: p.page_type,
      page_order: idx + 1,
      width_px: p.width_px,
      height_px: p.height_px,
    }))
    return {
      question_number: Number(questionNumber),
      marks: marks === '' ? null : Number(marks),
      topic_assignments: selectionsToAssignments(selected),
      pages: ordered,
    }
  }

  async function handleSave() {
    const num = Number(questionNumber)
    if (!Number.isInteger(num) || num < 1) {
      setError('Question number must be a positive whole number')
      return false
    }
    if (usedNumbers.includes(num)) {
      setError(`Question number ${num} already exists in this paper`)
      return false
    }
    setSaving(true)
    setError(null)
    try {
      const payload = buildPayload()
      const result = isNew
        ? await api.papers.addQuestion(paperId, payload)
        : await api.papers.updateQuestion(question.id, payload)
      onSaved(result)
      return true
    } catch (e) {
      setError(e.message)
      return false
    } finally {
      setSaving(false)
    }
  }

  // Expose save() so the parent's "Save all" can trigger each editor.
  const saveRef = useRef(handleSave)
  saveRef.current = handleSave
  useImperativeHandle(ref, () => ({ save: () => saveRef.current() }), [])

  async function handleDelete() {
    setDeleting(true)
    try {
      await api.papers.deleteQuestion(question.id)
      onDeleted(question.id)
    } catch (e) {
      setError(e.message)
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  async function handleRerunAi() {
    setAiBusy(true)
    setAiError(null)
    try {
      const res = await api.import.aiTopicsForQuestion(question.id)
      setSelected(res.selections || [])
      setMarks(res.marks != null ? String(res.marks) : '')
    } catch (e) {
      setAiError(e.message)
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1 text-sm text-gray-700">
            Q#
            <input
              type="number"
              value={questionNumber}
              onChange={(e) => setQuestionNumber(e.target.value)}
              className="w-16 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
          <label className="flex items-center gap-1 text-sm text-gray-700">
            Marks
            <input
              type="number"
              value={marks}
              onChange={(e) => setMarks(e.target.value)}
              placeholder="—"
              className="w-16 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          {!isNew && (
            <button
              type="button"
              onClick={handleRerunAi}
              disabled={aiBusy}
              className="text-xs px-2 py-1 rounded border border-gray-300 hover:border-blue-400 disabled:opacity-50 flex items-center gap-1"
            >
              {aiBusy && <Spinner size="sm" />} Re-run AI
            </button>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="text-xs px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 flex items-center gap-1"
          >
            {saving && <Spinner size="sm" />} {isNew ? 'Add question' : 'Save'}
          </button>
          {isNew ? (
            <button
              type="button"
              onClick={onCancelNew}
              className="text-xs px-3 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
            >Cancel</button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="text-xs px-3 py-1 rounded border border-gray-300 text-red-600 hover:border-red-400"
            >Delete</button>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-red-600 mb-2">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-4">
          <PageImageEditor label="Question pages" pageType="question" pages={qPages} onChange={setQPages} onExpand={onExpand} />
          <PageImageEditor label="Answer pages" pageType="answer" pages={aPages} onChange={setAPages} onExpand={onExpand} />
        </div>

        <div className="flex flex-col gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Topics</p>
            {selected.length === 0 && (
              <p className="text-sm text-gray-400 italic">No topics selected</p>
            )}
            {selected.map((sel, i) => {
              let label
              if (sel.subtopic_id != null) {
                const s = subtopicById?.get(sel.subtopic_id)
                label = s ? <><strong>{formatTopic(s.topic_number, s.topic_name)}</strong> » {s.name}</> : `Unknown subtopic ${sel.subtopic_id}`
              } else {
                const t = topicById?.get(sel.topic_id)
                label = t ? <strong>{formatTopic(t.topic_number, t.name)}</strong> : `Unknown topic ${sel.topic_id}`
              }
              return (
                <div key={i} className="flex items-start gap-2 mb-2 bg-blue-50 border border-blue-200 rounded-lg p-2">
                  <p className="text-sm text-gray-700 flex-grow">{label}</p>
                  <button
                    type="button"
                    onClick={() => removeTopic(i)}
                    className="text-gray-400 hover:text-red-600 text-lg flex-shrink-0 mt-0.5"
                    aria-label="Remove"
                  >×</button>
                </div>
              )
            })}
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Add topic</p>
            <TopicCombobox topics={topics || []} selected={selected} onAdd={addTopic} />
            {aiError && <p className="text-xs text-red-600 mt-1">{aiError}</p>}
          </div>
        </div>
      </div>

      <ConfirmDialog
        isOpen={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={handleDelete}
        itemName={`Question ${question.question_number}`}
        loading={deleting}
      />
    </div>
  )
}

export default forwardRef(QuestionEditor)
