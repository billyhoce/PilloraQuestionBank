import { useState, useEffect, useRef, Fragment } from 'react'
import LevelModal from '../modals/LevelModal'
import ConfirmDialog from '../../../components/ConfirmDialog'
import Spinner from '../../../components/Spinner'

function DragHandle() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
      <circle cx="5" cy="4" r="1.5" />
      <circle cx="11" cy="4" r="1.5" />
      <circle cx="5" cy="8" r="1.5" />
      <circle cx="11" cy="8" r="1.5" />
      <circle cx="5" cy="12" r="1.5" />
      <circle cx="11" cy="12" r="1.5" />
    </svg>
  )
}

export default function LevelsTab({ rows, schoolLevels, loading, onCreate, onUpdate, onDelete, onReorder }) {
  const [modal, setModal] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [reordering, setReordering] = useState(false)
  const [modalError, setModalError] = useState('')
  const [confirmError, setConfirmError] = useState('')
  const [orderedRows, setOrderedRows] = useState([])
  const [dropIndicatorIndex, setDropIndicatorIndex] = useState(null)
  const dragIndexRef = useRef(null)

  useEffect(() => {
    setOrderedRows(rows ? [...rows] : [])
  }, [rows])

  function getLabel(row) {
    const sl = schoolLevels.find((s) => s.id === row.school_level_id)
    return sl ? `${sl.name} ${row.name}` : row.name
  }

  function handleDragStart(e, index) {
    dragIndexRef.current = index
    e.dataTransfer.effectAllowed = 'move'
  }

  function handleDragOver(e, index) {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const rect = e.currentTarget.getBoundingClientRect()
    setDropIndicatorIndex(e.clientY < rect.top + rect.height / 2 ? index : index + 1)
  }

  async function handleDrop(e) {
    e.preventDefault()
    const insertAt = dropIndicatorIndex
    setDropIndicatorIndex(null)
    const dragIndex = dragIndexRef.current
    dragIndexRef.current = null
    if (dragIndex === null || insertAt === null) return
    if (insertAt === dragIndex || insertAt === dragIndex + 1) return

    const newRows = [...orderedRows]
    const [moved] = newRows.splice(dragIndex, 1)
    newRows.splice(dragIndex < insertAt ? insertAt - 1 : insertAt, 0, moved)
    setOrderedRows(newRows)

    setReordering(true)
    try {
      await onReorder(newRows.map((row, i) => ({ ...row, sort_order: i })))
    } finally {
      setReordering(false)
    }
  }

  function handleDragEnd() {
    dragIndexRef.current = null
    setDropIndicatorIndex(null)
  }

  async function handleSave(name, school_level_id) {
    setSaving(true)
    setModalError('')
    try {
      if (modal.mode === 'add') {
        await onCreate(name, orderedRows.length, school_level_id)
      } else {
        await onUpdate(modal.row.id, name, modal.row.sort_order, school_level_id)
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

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner size="lg" />
      </div>
    )
  }

  return (
    <div>
      <div className="flex justify-end mb-4">
        <button
          onClick={() => { setModal({ mode: 'add' }); setModalError('') }}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded"
        >
          + Add Level
        </button>
      </div>

      {orderedRows.length === 0 ? (
        <p className="text-sm text-gray-500 py-8 text-center">No items yet. Add one to get started.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-3 w-8" />
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Level
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white">
              {orderedRows.map((row, index) => (
                <Fragment key={row.id}>
                  <tr
                    draggable
                    onDragStart={(e) => handleDragStart(e, index)}
                    onDragOver={(e) => handleDragOver(e, index)}
                    onDrop={handleDrop}
                    onDragEnd={handleDragEnd}
                    style={dropIndicatorIndex === index ? { boxShadow: '0 -2px 0 0 #3B82F6' } : undefined}
                    className={`transition-colors select-none hover:bg-gray-50 ${index < orderedRows.length - 1 ? 'border-b border-gray-200' : ''}`}
                  >
                    <td className="px-3 py-3 text-gray-400 cursor-grab">
                      <DragHandle />
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {getLabel(row)}
                    </td>
                    <td className="px-4 py-3 text-right text-sm">
                      <button
                        onClick={() => { setModal({ mode: 'edit', row }); setModalError('') }}
                        className="text-blue-600 hover:text-blue-800 font-medium mr-4"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => { setConfirm(row); setConfirmError('') }}
                        className="text-red-600 hover:text-red-800 font-medium"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                </Fragment>
              ))}
              {dropIndicatorIndex === orderedRows.length && (
                <tr className="pointer-events-none" style={{ borderTop: 'none' }}>
                  <td colSpan={3} className="p-0">
                    <div className="h-0.5 bg-blue-500" />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {reordering && (
            <p className="text-center text-xs text-gray-400 py-2">Saving order…</p>
          )}
        </div>
      )}

      <LevelModal
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
        itemName={confirm ? getLabel(confirm) : ''}
        loading={deleting}
        error={confirmError}
      />
    </div>
  )
}
