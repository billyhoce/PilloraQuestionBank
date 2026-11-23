import { useState } from 'react'
import ReferenceTable from '../ReferenceTable'
import SubjectModal from '../modals/SubjectModal'
import ConfirmDialog from '../../../components/ConfirmDialog'

export default function SubjectsTab({ rows, loading, onCreate, onUpdate, onDelete }) {
  const [modal, setModal] = useState(null) // null | { mode: 'add' } | { mode: 'edit', row }
  const [confirm, setConfirm] = useState(null) // null | row
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [modalError, setModalError] = useState('')
  const [confirmError, setConfirmError] = useState('')

  const columns = [
    { key: 'name', label: 'Name' },
    { key: 'code', label: 'Code', render: (row) => row.code || '—' },
  ]

  async function handleSave(name, code) {
    setSaving(true)
    setModalError('')
    try {
      if (modal.mode === 'add') {
        await onCreate(name, code)
      } else {
        await onUpdate(modal.row.id, name, code)
      }
      setModal(null)
    } catch (err) {
      setModalError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    setConfirmError('')
    try {
      await onDelete(confirm.id)
      setConfirm(null)
    } catch (err) {
      setConfirmError(err.message)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div>
      <div className="flex justify-end mb-4">
        <button
          onClick={() => { setModal({ mode: 'add' }); setModalError('') }}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded"
        >
          + Add Subject
        </button>
      </div>

      <ReferenceTable
        columns={columns}
        rows={rows}
        loading={loading}
        onEdit={(row) => { setModal({ mode: 'edit', row }); setModalError('') }}
        onDelete={(row) => { setConfirm(row); setConfirmError('') }}
      />

      <SubjectModal
        isOpen={!!modal}
        onClose={() => setModal(null)}
        onSave={handleSave}
        initialValues={modal?.row}
        loading={saving}
        error={modalError}
      />

      <ConfirmDialog
        isOpen={!!confirm}
        onClose={() => setConfirm(null)}
        onConfirm={handleDelete}
        itemName={confirm?.name}
        loading={deleting}
        error={confirmError}
      />
    </div>
  )
}
