import React, { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import Spinner from '../../../components/Spinner'
import Modal from '../../../components/Modal'
import ErrorBanner from '../../../components/ErrorBanner'
import {
  topicsToRows,
  parseTopicsTsv,
  emptyTopicRow,
  emptySubtopicRow,
} from '../topicsPaste'

export default function TopicsTab({ subjects, streams }) {
  const [subjectId, setSubjectId] = useState('')
  const [streamId, setStreamId] = useState('')

  const [dbTopics, setDbTopics] = useState([]) // last-loaded server state
  const [rows, setRows] = useState([]) // editable grid
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [warn, setWarn] = useState(null) // null | { removedTopics, removedSubtopics }

  const filtersReady = subjectId && streamId

  // Load topics when both filters are selected.
  useEffect(() => {
    if (!filtersReady) {
      setDbTopics([])
      setRows([])
      setDirty(false)
      setError('')
      return
    }
    setLoading(true)
    setError('')
    api.topics.list(Number(subjectId), Number(streamId))
      .then((data) => {
        setDbTopics(data)
        setRows(topicsToRows(data))
        setDirty(false)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [subjectId, streamId]) // eslint-disable-line react-hooks/exhaustive-deps

  // --- Grid mutations ---

  function mutate(updater) {
    setRows(updater)
    setDirty(true)
    setError('')
  }

  function updateTopic(key, field, value) {
    mutate((prev) => prev.map((t) => (t.key === key ? { ...t, [field]: value } : t)))
  }

  function updateSubtopic(topicKey, subKey, value) {
    mutate((prev) => prev.map((t) => (
      t.key === topicKey
        ? { ...t, subtopics: t.subtopics.map((s) => (s.key === subKey ? { ...s, name: value } : s)) }
        : t
    )))
  }

  function addTopic() {
    const maxNo = rows.reduce((m, t) => Math.max(m, Number(t.topic_number) || 0), 0)
    mutate((prev) => [...prev, emptyTopicRow(maxNo + 1)])
  }

  function removeTopic(key) {
    mutate((prev) => prev.filter((t) => t.key !== key))
  }

  function addSubtopic(topicKey) {
    mutate((prev) => prev.map((t) => (
      t.key === topicKey ? { ...t, subtopics: [...t.subtopics, emptySubtopicRow()] } : t
    )))
  }

  function removeSubtopic(topicKey, subKey) {
    mutate((prev) => prev.map((t) => (
      t.key === topicKey ? { ...t, subtopics: t.subtopics.filter((s) => s.key !== subKey) } : t
    )))
  }

  // Intercept multi-cell pastes (TSV from Google Sheets) and replace the grid.
  function handlePaste(e) {
    const text = e.clipboardData.getData('text')
    if (!/[\t\n]/.test(text)) return // single value → let the focused input handle it
    e.preventDefault()
    setRows(parseTopicsTsv(text, dbTopics))
    setDirty(true)
    setError('')
  }

  // --- Save ---

  function computeRemovals() {
    const currentTopicIds = new Set(rows.filter((r) => r.id != null).map((r) => r.id))
    const removedTopics = []
    const removedSubtopics = []
    for (const t of dbTopics) {
      if (!currentTopicIds.has(t.id)) {
        removedTopics.push(t.name)
        continue
      }
      const row = rows.find((r) => r.id === t.id)
      const curSubIds = new Set(row.subtopics.filter((s) => s.id != null).map((s) => s.id))
      for (const s of t.subtopics || []) {
        if (!curSubIds.has(s.id)) removedSubtopics.push(`${s.name} — in "${t.name}"`)
      }
    }
    return { removedTopics, removedSubtopics }
  }

  function buildPayload() {
    return rows.map((t) => ({
      id: t.id,
      topic_number: Number(t.topic_number),
      name: t.name.trim(),
      subtopics: t.subtopics
        .filter((s) => s.name.trim() !== '')
        .map((s) => ({ id: s.id, name: s.name.trim() })),
    }))
  }

  function handleSaveClick() {
    setError('')
    for (const t of rows) {
      if (!t.name.trim()) {
        setError('Every topic needs a name.')
        return
      }
      const n = Number(t.topic_number)
      if (!Number.isInteger(n) || n < 1) {
        setError(`Topic "${t.name.trim() || '(unnamed)'}" needs a valid number (1 or more).`)
        return
      }
    }
    const { removedTopics, removedSubtopics } = computeRemovals()
    if (removedTopics.length || removedSubtopics.length) {
      setWarn({ removedTopics, removedSubtopics })
    } else {
      doSave()
    }
  }

  async function doSave() {
    setSaving(true)
    setError('')
    try {
      const data = await api.topics.sync(Number(subjectId), Number(streamId), buildPayload())
      setDbTopics(data)
      setRows(topicsToRows(data))
      setDirty(false)
      setWarn(null)
    } catch (err) {
      setWarn(null)
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  function revert() {
    setRows(topicsToRows(dbTopics))
    setDirty(false)
    setError('')
  }

  return (
    <div>
      {/* Filter bar */}
      <div className="flex flex-wrap gap-4 mb-6 items-end">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wider">Subject</label>
          <select
            value={subjectId}
            onChange={(e) => { setSubjectId(e.target.value); setStreamId('') }}
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]"
          >
            <option value="">Select subject…</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wider">Stream</label>
          <select
            value={streamId}
            onChange={(e) => setStreamId(e.target.value)}
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[160px]"
          >
            <option value="">Select stream…</option>
            {streams.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
      </div>

      {!subjectId && (
        <p className="text-sm text-gray-500 py-8 text-center">Select a subject and stream to edit topics.</p>
      )}
      {subjectId && !streamId && (
        <p className="text-sm text-gray-500 py-8 text-center">Also select a stream to edit topics.</p>
      )}

      {filtersReady && loading && (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      )}

      {filtersReady && !loading && (
        <div>
          <p className="text-xs text-gray-500 mb-3">
            Edit cells directly, or paste rows copied from Google Sheets (Topic No. / Topic Name / Sub-Topic)
            anywhere in the table to fill it. Click <strong>Save all</strong> to apply.
          </p>

          <ErrorBanner message={error} />

          <div className="overflow-x-auto mt-3" onPaste={handlePaste}>
            <table className="min-w-full border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-b border-gray-200 w-20">Topic No.</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-b border-gray-200 w-64">Topic Name</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-b border-gray-200">Sub-Topic</th>
                  <th className="px-3 py-2 border-b border-gray-200 w-24" />
                </tr>
              </thead>
              <tbody>
                {rows.map((topic) => {
                  const rowCount = Math.max(topic.subtopics.length, 1)
                  return (
                    <React.Fragment key={topic.key}>
                      {Array.from({ length: rowCount }).map((_, i) => {
                        const sub = topic.subtopics[i]
                        return (
                          <tr key={sub ? sub.key : `empty-${topic.key}`} className="border-b border-gray-200">
                            {i === 0 && (
                              <>
                                <td rowSpan={rowCount} className="px-2 py-1 align-top border-r border-gray-200">
                                  <input
                                    type="number"
                                    min="1"
                                    value={topic.topic_number}
                                    onChange={(e) => updateTopic(topic.key, 'topic_number', e.target.value)}
                                    className="w-16 border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  />
                                </td>
                                <td rowSpan={rowCount} className="px-2 py-1 align-top border-r border-gray-200">
                                  <input
                                    type="text"
                                    value={topic.name}
                                    onChange={(e) => updateTopic(topic.key, 'name', e.target.value)}
                                    placeholder="Topic name"
                                    className="w-full border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  />
                                  <div className="mt-2 flex gap-3">
                                    <button
                                      type="button"
                                      onClick={() => addSubtopic(topic.key)}
                                      className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                                    >
                                      + Subtopic
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => removeTopic(topic.key)}
                                      className="text-xs text-red-600 hover:text-red-800 font-medium"
                                    >
                                      Delete topic
                                    </button>
                                  </div>
                                </td>
                              </>
                            )}
                            <td className="px-2 py-1">
                              {sub ? (
                                <input
                                  type="text"
                                  value={sub.name}
                                  onChange={(e) => updateSubtopic(topic.key, sub.key, e.target.value)}
                                  placeholder="Subtopic name"
                                  className="w-full border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                />
                              ) : (
                                <span className="text-sm text-gray-400 italic">No subtopics</span>
                              )}
                            </td>
                            <td className="px-2 py-1 text-right">
                              {sub && (
                                <button
                                  type="button"
                                  onClick={() => removeSubtopic(topic.key, sub.key)}
                                  className="text-gray-400 hover:text-red-600 text-sm"
                                  title="Remove subtopic"
                                >
                                  ✕
                                </button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </React.Fragment>
                  )
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center text-sm text-gray-400">
                      No topics yet. Add a topic row or paste from Google Sheets.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <button
              type="button"
              onClick={addTopic}
              className="text-sm border border-gray-300 rounded px-4 py-2 text-gray-700 hover:bg-gray-50"
            >
              + Add topic row
            </button>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={revert}
                disabled={!dirty || saving}
                className="text-sm border border-gray-300 rounded px-4 py-2 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Revert
              </button>
              <button
                type="button"
                onClick={handleSaveClick}
                disabled={!dirty || saving}
                className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded flex items-center gap-2"
              >
                {saving && <Spinner size="sm" />}
                Save all
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Deletion warning */}
      <Modal isOpen={!!warn} onClose={() => !saving && setWarn(null)} title="Remove labels from questions?">
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            Saving will delete the following. Any questions currently labelled with them will lose those
            labels (the questions themselves are kept). This cannot be undone.
          </p>
          {warn?.removedTopics.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">Topics</p>
              <ul className="list-disc list-inside text-sm text-gray-700 max-h-32 overflow-y-auto">
                {warn.removedTopics.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}
          {warn?.removedSubtopics.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">Subtopics</p>
              <ul className="list-disc list-inside text-sm text-gray-700 max-h-32 overflow-y-auto">
                {warn.removedSubtopics.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}
          <ErrorBanner message={error} />
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setWarn(null)}
              disabled={saving}
              className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={doSave}
              disabled={saving}
              className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
            >
              {saving && <Spinner size="sm" />}
              Delete & save
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
