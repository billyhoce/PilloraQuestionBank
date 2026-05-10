import { useEffect, useState } from 'react'
import Modal from '../../../components/Modal'
import ErrorBanner from '../../../components/ErrorBanner'
import Spinner from '../../../components/Spinner'

export default function SubtopicModal({ isOpen, onClose, onSave, initialValues, topicName, loading, error }) {
  const [name, setName] = useState('')

  useEffect(() => {
    if (isOpen) setName(initialValues?.name ?? '')
  }, [isOpen, initialValues])

  async function handleSubmit(e) {
    e.preventDefault()
    await onSave(name.trim())
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={initialValues ? 'Edit subtopic' : 'Add subtopic'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <ErrorBanner message={error} />
        <div className="bg-gray-50 rounded px-3 py-2 text-sm text-gray-600">
          <span className="font-medium">Topic:</span> {topicName}
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            autoFocus
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
