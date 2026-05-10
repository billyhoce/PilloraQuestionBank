import React, { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import Spinner from '../../../components/Spinner'
import ConfirmDialog from '../../../components/ConfirmDialog'
import TopicModal from '../modals/TopicModal'
import SubtopicModal from '../modals/SubtopicModal'

export default function TopicsTab({ subjects, streams }) {
  const [subjectId, setSubjectId] = useState('')
  const [streamId, setStreamId] = useState('')

  const [topics, setTopics] = useState([])
  const [topicsLoading, setTopicsLoading] = useState(false)

  // { [topicId]: Subtopic[] }
  const [subtopicsMap, setSubtopicsMap] = useState({})
  const [subtopicsLoading, setSubtopicsLoading] = useState({}) // { [topicId]: bool }
  const [expandedTopicId, setExpandedTopicId] = useState(null)

  // Topic modal
  const [topicModal, setTopicModal] = useState(null) // null | { mode, row? }
  const [topicSaving, setTopicSaving] = useState(false)
  const [topicModalError, setTopicModalError] = useState('')

  // Subtopic modal
  const [subtopicModal, setSubtopicModal] = useState(null) // null | { mode, topicId, topicName, row? }
  const [subtopicSaving, setSubtopicSaving] = useState(false)
  const [subtopicModalError, setSubtopicModalError] = useState('')

  // Confirm dialogs
  const [topicConfirm, setTopicConfirm] = useState(null) // null | row
  const [topicDeleting, setTopicDeleting] = useState(false)
  const [topicConfirmError, setTopicConfirmError] = useState('')

  const [subtopicConfirm, setSubtopicConfirm] = useState(null) // null | { subtopic, topicId }
  const [subtopicDeleting, setSubtopicDeleting] = useState(false)
  const [subtopicConfirmError, setSubtopicConfirmError] = useState('')

  const selectedSubject = subjects.find((s) => s.id === Number(subjectId))
  const selectedStream = streams.find((s) => s.id === Number(streamId))

  // Fetch topics when both filters are selected
  useEffect(() => {
    if (!subjectId || !streamId) {
      setTopics([])
      setExpandedTopicId(null)
      setSubtopicsMap({})
      return
    }
    setTopicsLoading(true)
    api.topics.list(Number(subjectId), Number(streamId))
      .then(setTopics)
      .catch(() => setTopics([]))
      .finally(() => setTopicsLoading(false))
  }, [subjectId, streamId])

  async function fetchSubtopics(topicId) {
    if (subtopicsMap[topicId] !== undefined) return
    setSubtopicsLoading((prev) => ({ ...prev, [topicId]: true }))
    try {
      const data = await api.subtopics.list(topicId)
      setSubtopicsMap((prev) => ({ ...prev, [topicId]: data }))
    } catch {
      setSubtopicsMap((prev) => ({ ...prev, [topicId]: [] }))
    } finally {
      setSubtopicsLoading((prev) => ({ ...prev, [topicId]: false }))
    }
  }

  function toggleExpand(topicId) {
    if (expandedTopicId === topicId) {
      setExpandedTopicId(null)
    } else {
      setExpandedTopicId(topicId)
      fetchSubtopics(topicId)
    }
  }

  async function refreshTopics() {
    if (!subjectId || !streamId) return
    const data = await api.topics.list(Number(subjectId), Number(streamId))
    setTopics(data)
  }

  async function refreshSubtopics(topicId) {
    const data = await api.subtopics.list(topicId)
    setSubtopicsMap((prev) => ({ ...prev, [topicId]: data }))
  }

  // --- Topic CRUD ---

  async function handleTopicSave(name, topicNumber) {
    setTopicSaving(true)
    setTopicModalError('')
    try {
      if (topicModal.mode === 'add') {
        await api.topics.create(Number(subjectId), Number(streamId), name, topicNumber)
      } else {
        await api.topics.update(topicModal.row.id, Number(subjectId), Number(streamId), name, topicNumber)
      }
      setTopicModal(null)
      await refreshTopics()
    } catch (err) {
      setTopicModalError(err.message)
    } finally {
      setTopicSaving(false)
    }
  }

  async function handleTopicDelete() {
    setTopicDeleting(true)
    setTopicConfirmError('')
    try {
      await api.topics.delete(topicConfirm.id)
      setTopicConfirm(null)
      if (expandedTopicId === topicConfirm.id) setExpandedTopicId(null)
      await refreshTopics()
    } catch (err) {
      setTopicConfirmError(err.message)
    } finally {
      setTopicDeleting(false)
    }
  }

  // --- Subtopic CRUD ---

  async function handleSubtopicSave(name) {
    setSubtopicSaving(true)
    setSubtopicModalError('')
    try {
      if (subtopicModal.mode === 'add') {
        await api.subtopics.create(subtopicModal.topicId, name)
      } else {
        await api.subtopics.update(subtopicModal.row.id, subtopicModal.topicId, name)
      }
      setSubtopicModal(null)
      // invalidate cache so next expand re-fetches
      setSubtopicsMap((prev) => {
        const next = { ...prev }
        delete next[subtopicModal.topicId]
        return next
      })
      await refreshSubtopics(subtopicModal.topicId)
    } catch (err) {
      setSubtopicModalError(err.message)
    } finally {
      setSubtopicSaving(false)
    }
  }

  async function handleSubtopicDelete() {
    setSubtopicDeleting(true)
    setSubtopicConfirmError('')
    try {
      await api.subtopics.delete(subtopicConfirm.subtopic.id)
      const topicId = subtopicConfirm.topicId
      setSubtopicConfirm(null)
      setSubtopicsMap((prev) => {
        const next = { ...prev }
        delete next[topicId]
        return next
      })
      await refreshSubtopics(topicId)
    } catch (err) {
      setSubtopicConfirmError(err.message)
    } finally {
      setSubtopicDeleting(false)
    }
  }

  const filtersReady = subjectId && streamId

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
        {filtersReady && (
          <button
            onClick={() => { setTopicModal({ mode: 'add' }); setTopicModalError('') }}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded"
          >
            + Add Topic
          </button>
        )}
      </div>

      {/* Content area */}
      {!subjectId && (
        <p className="text-sm text-gray-500 py-8 text-center">Select a subject and stream to view topics.</p>
      )}
      {subjectId && !streamId && (
        <p className="text-sm text-gray-500 py-8 text-center">Also select a stream to view topics.</p>
      )}
      {filtersReady && topicsLoading && (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      )}
      {filtersReady && !topicsLoading && topics.length === 0 && (
        <p className="text-sm text-gray-500 py-8 text-center">
          No topics yet for this combination. Use "+ Add Topic" above to create one.
        </p>
      )}
      {filtersReady && !topicsLoading && topics.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="w-10 px-4 py-3" />
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">#</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {topics.map((topic) => (
                <React.Fragment key={topic.id}>
                  <tr className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-center">
                      <button
                        onClick={() => toggleExpand(topic.id)}
                        className="text-gray-400 hover:text-gray-600 text-lg leading-none"
                        title={expandedTopicId === topic.id ? 'Collapse subtopics' : 'Expand subtopics'}
                      >
                        {expandedTopicId === topic.id ? '▼' : '▶'}
                      </button>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">{topic.topic_number}</td>
                    <td className="px-4 py-3 text-sm text-gray-900">{topic.name}</td>
                    <td className="px-4 py-3 text-right text-sm">
                      <button
                        onClick={() => { setTopicModal({ mode: 'edit', row: topic }); setTopicModalError('') }}
                        className="text-blue-600 hover:text-blue-800 font-medium mr-4"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => { setTopicConfirm(topic); setTopicConfirmError('') }}
                        className="text-red-600 hover:text-red-800 font-medium"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>

                  {expandedTopicId === topic.id && (
                    <tr>
                      <td colSpan={4} className="bg-gray-50 px-8 py-4">
                        {subtopicsLoading[topic.id] ? (
                          <div className="flex justify-center py-4"><Spinner size="md" /></div>
                        ) : (
                          <SubtopicsInline
                            subtopics={subtopicsMap[topic.id] ?? []}
                            topic={topic}
                            onAdd={() => {
                              setSubtopicModal({ mode: 'add', topicId: topic.id, topicName: topic.name })
                              setSubtopicModalError('')
                            }}
                            onEdit={(sub) => {
                              setSubtopicModal({ mode: 'edit', topicId: topic.id, topicName: topic.name, row: sub })
                              setSubtopicModalError('')
                            }}
                            onDelete={(sub) => {
                              setSubtopicConfirm({ subtopic: sub, topicId: topic.id })
                              setSubtopicConfirmError('')
                            }}
                          />
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Topic modals */}
      <TopicModal
        isOpen={!!topicModal}
        onClose={() => setTopicModal(null)}
        onSave={handleTopicSave}
        initialValues={topicModal?.row}
        subjectName={selectedSubject?.name ?? ''}
        streamName={selectedStream?.name ?? ''}
        loading={topicSaving}
        error={topicModalError}
      />
      <ConfirmDialog
        isOpen={!!topicConfirm}
        onClose={() => setTopicConfirm(null)}
        onConfirm={handleTopicDelete}
        itemName={topicConfirm?.name}
        loading={topicDeleting}
        error={topicConfirmError}
      />

      {/* Subtopic modals */}
      <SubtopicModal
        isOpen={!!subtopicModal}
        onClose={() => setSubtopicModal(null)}
        onSave={handleSubtopicSave}
        initialValues={subtopicModal?.row}
        topicName={subtopicModal?.topicName ?? ''}
        loading={subtopicSaving}
        error={subtopicModalError}
      />
      <ConfirmDialog
        isOpen={!!subtopicConfirm}
        onClose={() => setSubtopicConfirm(null)}
        onConfirm={handleSubtopicDelete}
        itemName={subtopicConfirm?.subtopic?.name}
        loading={subtopicDeleting}
        error={subtopicConfirmError}
      />
    </div>
  )
}

function SubtopicsInline({ subtopics, topic, onAdd, onEdit, onDelete }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Subtopics of "{topic.name}"
        </span>
        <button
          onClick={onAdd}
          className="text-xs bg-blue-600 hover:bg-blue-700 text-white font-medium px-3 py-1.5 rounded"
        >
          + Add Subtopic
        </button>
      </div>

      {subtopics.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No subtopics yet.</p>
      ) : (
        <table className="min-w-full divide-y divide-gray-200">
          <tbody className="divide-y divide-gray-200">
            {subtopics.map((sub) => (
              <tr key={sub.id} className="hover:bg-white">
                <td className="py-2 pr-4 text-sm text-gray-800">{sub.name}</td>
                <td className="py-2 text-right text-sm">
                  <button
                    onClick={() => onEdit(sub)}
                    className="text-blue-600 hover:text-blue-800 font-medium mr-4"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => onDelete(sub)}
                    className="text-red-600 hover:text-red-800 font-medium"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
