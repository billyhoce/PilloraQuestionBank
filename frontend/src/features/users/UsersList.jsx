import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { useSiteConfig } from '../../context/SiteConfigContext'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'
import ConfirmDialog from '../../components/ConfirmDialog'
import { fullName } from '../../utils/userName'
import InviteUserModal from './InviteUserModal'

// The stored role value 'public' is shown as "Normal" in the UI. Premium is not
// a role — it is the set of school levels in the Premium Access column.
const ROLE_OPTIONS = [
  { value: 'public', label: 'Normal' },
  { value: 'admin', label: 'Admin' },
]

function formatDate(value) {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function Dash() {
  return <span className="text-gray-400">—</span>
}

// How the account signs in. "Invited" means an admin pre-created it and nobody
// has claimed it yet, so it has no credentials at all.
function StatusBadge({ user }) {
  const { className, label, title } = user.is_invited
    ? {
        className: 'border-amber-300 text-amber-800 bg-amber-50',
        label: 'Invited',
        title: 'Pre-added by an admin — premium is ready but nobody has signed up on this address yet',
      }
    : user.has_password && user.has_google
      ? { className: 'border-gray-300 text-gray-700 bg-gray-50', label: 'Password + Google', title: 'Can sign in either way' }
      : user.has_google
        ? { className: 'border-blue-300 text-blue-700 bg-blue-50', label: 'Google', title: 'Signs in with Google' }
        : { className: 'border-gray-300 text-gray-700 bg-gray-50', label: 'Password', title: 'Signs in with a password' }

  return (
    <span title={title} className={`text-[10px] px-1.5 py-0.5 border rounded-full whitespace-nowrap ${className}`}>
      {label}
    </span>
  )
}

export default function UsersList() {
  const { user: currentUser } = useAuth()
  const { protectImages, setConfig } = useSiteConfig()
  const [rows, setRows] = useState([])
  const [schoolLevels, setSchoolLevels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [savingId, setSavingId] = useState(null)
  const [rowError, setRowError] = useState(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [deleting, setDeleting] = useState(null) // the row pending confirmation
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState(null)
  const [settingsBusy, setSettingsBusy] = useState(false)
  const [settingsError, setSettingsError] = useState(null)

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

  async function handleDelete() {
    setDeleteBusy(true)
    setDeleteError(null)
    try {
      await api.users.remove(deleting.id)
      setRows((rs) => rs.filter((r) => r.id !== deleting.id))
      setDeleting(null)
    } catch (e) {
      setDeleteError(e.message)
    } finally {
      setDeleteBusy(false)
    }
  }

  async function handleProtectImages(checked) {
    setSettingsBusy(true)
    setSettingsError(null)
    try {
      // A partial update — the About content is edited elsewhere and must not be
      // resent from here, or one page would overwrite the other's value.
      setConfig(await api.siteConfig.update({ protect_images: checked }))
    } catch (e) {
      setSettingsError(e.message)
    } finally {
      setSettingsBusy(false)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-12"><Spinner size="lg" /></div>
  }

  const th = 'px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap'

  return (
    <div className="max-w-[90%] mx-auto space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-gray-900">User Management</h1>
        <button
          type="button"
          onClick={() => setInviteOpen(true)}
          className="text-sm font-medium px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          + Add user by email
        </button>
      </div>

      {error && <ErrorBanner message={error} />}

      <section className="bg-white border border-gray-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-2">Site settings</h2>
        <label className="flex items-start gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={protectImages}
            disabled={settingsBusy}
            onChange={(e) => handleProtectImages(e.target.checked)}
            className="mt-0.5 rounded border-gray-300 disabled:opacity-50"
          />
          <span>
            Discourage copying of question images
            <span className="block text-xs text-gray-500">
              Blocks right-click, dragging and the mobile long-press menu on the Question Bank,
              Generate and question detail views. Admins are unaffected. This is a deterrent, not
              protection — images are still reachable through the browser's developer tools.
            </span>
          </span>
        </label>
        {settingsError && <div className="mt-2 text-xs text-red-600">{settingsError}</div>}
      </section>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className={th}>Name</th>
              <th className={th}>Email</th>
              <th className={th}>Sign-in</th>
              <th className={th}>Joined</th>
              <th className={th}>Last login</th>
              <th className={th}>Papers</th>
              <th className={th}>Tier</th>
              <th className={th}>Premium Access</th>
              <th className={th}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {rows.map((u) => {
              const isSelf = currentUser?.id === u.id
              const held = new Set((u.premium_school_levels || []).map((sl) => sl.id))
              return (
                <tr key={u.id} className="hover:bg-gray-50">
                  <td className="px-3 py-3 text-sm text-gray-900">
                    {fullName(u) || <Dash />}
                    {isSelf && <span className="ml-2 text-xs text-gray-400">(you)</span>}
                  </td>
                  <td className="px-3 py-3 text-sm text-gray-900">{u.email}</td>
                  <td className="px-3 py-3 text-sm"><StatusBadge user={u} /></td>
                  <td className="px-3 py-3 text-sm text-gray-600 whitespace-nowrap">
                    {formatDate(u.created_at) || <Dash />}
                  </td>
                  <td className="px-3 py-3 text-sm text-gray-600 whitespace-nowrap">
                    {formatDate(u.last_login_at) || <span className="text-gray-400">Never</span>}
                  </td>
                  <td className="px-3 py-3 text-sm text-gray-600">{u.papers_generated ?? 0}</td>
                  <td className="px-3 py-3 text-sm">
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
                  <td className="px-3 py-3 text-sm">
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
                  <td className="px-3 py-3 text-sm text-right">
                    {!isSelf && (
                      <button
                        type="button"
                        onClick={() => { setDeleting(u); setDeleteError(null) }}
                        aria-label={`Delete ${u.email}`}
                        className="text-xs text-red-600 hover:text-red-800 hover:underline"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <InviteUserModal
        isOpen={inviteOpen}
        onClose={() => setInviteOpen(false)}
        schoolLevels={schoolLevels}
        onCreated={(created) => setRows((rs) => [...rs, created])}
      />

      <ConfirmDialog
        isOpen={!!deleting}
        onClose={() => { setDeleting(null); setDeleteError(null) }}
        onConfirm={handleDelete}
        itemName={deleting?.email || ''}
        loading={deleteBusy}
        error={deleteError}
      />
    </div>
  )
}
