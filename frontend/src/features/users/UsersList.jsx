import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'
import { fullName } from '../../utils/userName'

// The stored role value 'public' is shown as "Normal" in the UI. Premium is not
// a role — it is the set of school levels in the Premium Access column.
const ROLE_OPTIONS = [
  { value: 'public', label: 'Normal' },
  { value: 'admin', label: 'Admin' },
]

export default function UsersList() {
  const { user: currentUser } = useAuth()
  const [rows, setRows] = useState([])
  const [schoolLevels, setSchoolLevels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [savingId, setSavingId] = useState(null)
  const [rowError, setRowError] = useState(null)

  const refresh = useCallback(() => {
    setLoading(true)
    Promise.all([api.users.list(), api.schoolLevels.list()])
      .then(([users, levels]) => {
        setRows(users)
        setSchoolLevels(levels || [])
        setError(null)
      })
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

  // Ticking a box sends the whole resulting set, since the endpoint replaces
  // rather than merges — one call both grants and revokes.
  async function handlePremiumToggle(user, schoolLevel, checked) {
    const next = checked
      ? [...(user.premium_school_levels || []), schoolLevel]
      : (user.premium_school_levels || []).filter((sl) => sl.id !== schoolLevel.id)

    setSavingId(user.id)
    setRowError(null)
    const prev = rows
    setRows((rs) => rs.map((r) => (r.id === user.id ? { ...r, premium_school_levels: next } : r)))
    try {
      await api.users.setPremiumSchoolLevels(user.id, next.map((sl) => sl.id))
    } catch (e) {
      setRows(prev)  // revert
      setRowError({ id: user.id, message: e.message })
    } finally {
      setSavingId(null)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-12"><Spinner size="lg" /></div>
  }

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-lg font-semibold text-gray-900 mb-4">User Management</h1>

      {error && <div className="mb-4"><ErrorBanner message={error} /></div>}

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Email</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Tier</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Premium Access</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {rows.map((u) => {
              const isSelf = currentUser?.id === u.id
              const held = new Set((u.premium_school_levels || []).map((sl) => sl.id))
              return (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {fullName(u) || <span className="text-gray-400">—</span>}
                    {isSelf && <span className="ml-2 text-xs text-gray-400">(you)</span>}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">{u.email}</td>
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
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {u.role === 'admin' ? (
                      <span className="text-xs text-gray-400">All access</span>
                    ) : (
                      <div className="flex flex-wrap gap-3">
                        {schoolLevels.map((sl) => (
                          <label key={sl.id} className="flex items-center gap-1.5 text-sm text-gray-700">
                            <input
                              type="checkbox"
                              checked={held.has(sl.id)}
                              disabled={savingId === u.id}
                              onChange={(e) => handlePremiumToggle(u, sl, e.target.checked)}
                              aria-label={`${sl.name} premium for ${u.email}`}
                              className="rounded border-gray-300 disabled:opacity-50"
                            />
                            {sl.name}
                          </label>
                        ))}
                      </div>
                    )}
                    {rowError?.id === u.id && (
                      <div className="mt-1 text-xs text-red-600">{rowError.message}</div>
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
