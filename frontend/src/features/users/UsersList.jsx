import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'

// The stored role value 'public' is shown as "Normal" in the UI; 'premium' and
// 'admin' map to themselves.
const ROLE_OPTIONS = [
  { value: 'public', label: 'Normal' },
  { value: 'premium', label: 'Premium' },
  { value: 'admin', label: 'Admin' },
]

export default function UsersList() {
  const { user: currentUser } = useAuth()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [savingId, setSavingId] = useState(null)
  const [rowError, setRowError] = useState(null)

  const refresh = useCallback(() => {
    setLoading(true)
    api.users.list()
      .then((data) => { setRows(data); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function handleRoleChange(userId, role) {
    setSavingId(userId)
    setRowError(null)
    const prev = rows
    // Optimistic update.
    setRows((rs) => rs.map((r) => (r.id === userId ? { ...r, role } : r)))
    try {
      await api.users.updateRole(userId, role)
    } catch (e) {
      setRows(prev)  // revert
      setRowError({ id: userId, message: e.message })
    } finally {
      setSavingId(null)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-12"><Spinner size="lg" /></div>
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-lg font-semibold text-gray-900 mb-4">User Management</h1>

      {error && <div className="mb-4"><ErrorBanner message={error} /></div>}

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Tier</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {rows.map((u) => {
              const isSelf = currentUser?.id === u.id
              return (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {u.email}
                    {isSelf && <span className="ml-2 text-xs text-gray-400">(you)</span>}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <select
                      value={u.role}
                      disabled={isSelf || savingId === u.id}
                      onChange={(e) => handleRoleChange(u.id, e.target.value)}
                      aria-label={`Tier for ${u.email}`}
                      className="border border-gray-300 rounded px-2 py-1 text-sm disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {ROLE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                    {rowError?.id === u.id && (
                      <span className="ml-2 text-xs text-red-600">{rowError.message}</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
