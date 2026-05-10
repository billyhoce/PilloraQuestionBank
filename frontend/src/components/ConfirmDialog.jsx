import Modal from './Modal'
import ErrorBanner from './ErrorBanner'
import Spinner from './Spinner'

export default function ConfirmDialog({ isOpen, onClose, onConfirm, itemName, loading, error }) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Confirm delete">
      <div className="space-y-4">
        <p className="text-sm text-gray-700">
          Are you sure you want to delete <strong>{itemName}</strong>? This cannot be undone.
        </p>
        <ErrorBanner message={error} />
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            disabled={loading}
            className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
          >
            {loading && <Spinner size="sm" />}
            Delete
          </button>
        </div>
      </div>
    </Modal>
  )
}
