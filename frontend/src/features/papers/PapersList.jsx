import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import ReferenceTable from '../reference/ReferenceTable'
import ConfirmDialog from '../../components/ConfirmDialog'
import ErrorBanner from '../../components/ErrorBanner'

const columns = [
  { key: 'subject_name', label: 'Subject' },
  { key: 'stream_name', label: 'Stream' },
  { key: 'level_name', label: 'Level' },
  { key: 'school_name', label: 'School' },
  { key: 'exam_type_name', label: 'Exam' },
  { key: 'year', label: 'Year' },
  { key: 'paper_number', label: 'Paper' },
  { key: 'question_count', label: 'Questions' },
]

export default function PapersList() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [toDelete, setToDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)

  const refresh = useCallback(() => {
    setLoading(true)
    api.papers.list({ page_size: 200 })
      .then((res) => { setRows(res.items); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function handleDelete() {
    setDeleting(true)
    setDeleteError(null)
    try {
      await api.papers.remove(toDelete.id)
      setToDelete(null)
      refresh()
    } catch (e) {
      setDeleteError(e.message)
    } finally {
      setDeleting(false)
    }
  }

  function describe(p) {
    return `${p.subject_name} ${p.stream_name} ${p.year} ${p.exam_type_name} Paper ${p.paper_number}`
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-900">Papers</h1>
        <Link
          to="/admin/import"
          className="text-sm px-3 py-1.5 rounded border border-gray-300 hover:border-blue-400"
        >
          + Import paper
        </Link>
      </div>

      {error && <div className="mb-4"><ErrorBanner message={error} /></div>}

      <ReferenceTable
        columns={columns}
        rows={rows}
        loading={loading}
        onEdit={(row) => navigate(`/admin/papers/${row.id}`)}
        onDelete={(row) => { setDeleteError(null); setToDelete(row) }}
      />

      <ConfirmDialog
        isOpen={!!toDelete}
        onClose={() => setToDelete(null)}
        onConfirm={handleDelete}
        itemName={toDelete ? describe(toDelete) : ''}
        loading={deleting}
        error={deleteError}
      />
    </div>
  )
}
