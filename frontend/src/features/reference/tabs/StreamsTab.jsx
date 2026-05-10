import { useState } from 'react'
import ReferenceTable from '../ReferenceTable'
import StreamModal from '../modals/StreamModal'
import ConfirmDialog from '../../../components/ConfirmDialog'

export default function StreamsTab({ rows, schoolLevels, loading, onCreate, onUpdate, onDelete }) {
  const [modal, setModal] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [modalError, setModalError] = useState('')
  const [confirmError, setConfirmError] = useState('')

  const columns = [
    { key: 'name', label: 'Name' },
    {
      key: 'school_level_id',
      label: 'School Level',
      render: (row) => schoolLevels.find((sl) => sl.id === row.school_level_id)?.name ?? '—',
    },
  ]

  async function handleSave(name, school_level_id) {
    setSaving(true)
    setModalError('')
    try {
      if (modal.mode === 'add') {
        await onCreate(name, school_level_id)
      } else {
        await onUpdate(modal.row.id, name, school_level_id)
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
          + Add Stream
        </button>
      </div>

      <ReferenceTable
        columns={columns}
        rows={rows}
        loading={loading}
        onEdit={(row) => { setModal({ mode: 'edit', row }); setModalError('') }}
        onDelete={(row) => { setConfirm(row); setConfirmError('') }}
      />

      <StreamModal
        isOpen={!!modal}
        onClose={() => setModal(null)}
        onSave={handleSave}
        initialValues={modal?.row}
        schoolLevels={schoolLevels}
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
