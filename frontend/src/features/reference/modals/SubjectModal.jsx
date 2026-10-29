import { useState } from 'react'
import Modal from '../../../components/Modal'
import ErrorBanner from '../../../components/ErrorBanner'
import Spinner from '../../../components/Spinner'

const inputCls = 'w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

// A subject's name, and its optional code: how covers and filenames may name it, shown only to the
// AI that reads paper covers.
export default function SubjectModal({ isOpen, onClose, onSave, initialValues, loading, error }) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={initialValues ? 'Edit Subject' : 'Add Subject'}>
      {/* mounted per opening, so the fields start from the row being edited */}
      <SubjectForm key={initialValues?.id ?? 'new'} initialValues={initialValues} onClose={onClose}
        onSave={onSave} loading={loading} error={error} />
    </Modal>
  )
}

function SubjectForm({ initialValues, onClose, onSave, loading, error }) {
  const [name, setName] = useState(initialValues?.name ?? '')
  const [code, setCode] = useState(initialValues?.code ?? '')

  async function handleSubmit(e) {
    e.preventDefault()
    await onSave(name.trim(), code.trim() || null)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <ErrorBanner message={error} />
      <div>
        <label htmlFor="subject-name" className="block text-sm font-medium text-gray-700 mb-1">Name</label>
        <input id="subject-name" type="text" required value={name} onChange={(e) => setName(e.target.value)}
          className={inputCls} autoFocus />
      </div>
      <div>
        <label htmlFor="subject-code" className="block text-sm font-medium text-gray-700 mb-1">Code (optional)</label>
        <input id="subject-code" type="text" maxLength={32} value={code} onChange={(e) => setCode(e.target.value)}
          aria-describedby="subject-code-hint" className={inputCls} />
        <p id="subject-code-hint" className="mt-1 text-xs text-gray-500">
          How paper covers or filenames may name it, e.g. 4052 or EM. Only shown to the AI that reads paper covers.
        </p>
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
  )
}
