import { useEffect, useState } from 'react'
import Modal from '../../../components/Modal'
import ErrorBanner from '../../../components/ErrorBanner'
import Spinner from '../../../components/Spinner'

export default function TopicModal({ isOpen, onClose, onSave, initialValues, subjectName, streamName, loading, error }) {
  const [topicNumber, setTopicNumber] = useState('')
  const [name, setName] = useState('')

  useEffect(() => {
    if (isOpen) {
      setTopicNumber(initialValues?.topic_number != null ? String(initialValues.topic_number) : '')
      setName(initialValues?.name ?? '')
    }
  }, [isOpen, initialValues])

  async function handleSubmit(e) {
    e.preventDefault()
    await onSave(name.trim(), Number(topicNumber))
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={initialValues ? 'Edit topic' : 'Add topic'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <ErrorBanner message={error} />
        <div className="bg-gray-50 rounded px-3 py-2 text-sm text-gray-600 space-y-1">
          <div><span className="font-medium">Subject:</span> {subjectName}</div>
          <div><span className="font-medium">Stream:</span> {streamName}</div>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Topic Number</label>
          <input
            type="number"
            required
            min="1"
            value={topicNumber}
            onChange={(e) => setTopicNumber(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            autoFocus
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
          >
            {loading && <Spinner size="sm" />}
            Save
          </button>
        </div>
      </form>
    </Modal>
  )
}
