import { useState } from 'react'
import { api } from '../../api/client'
import Modal from '../../components/Modal'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'

// Pre-create an account so its premium access is live before the customer signs
// up. The row holds no password — it is claimed when they register or sign in
// with Google on the same address.
export default function InviteUserModal({ isOpen, onClose, schoolLevels, onCreated }) {
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [levelIds, setLevelIds] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  function reset() {
    setEmail('')
    setFirstName('')
    setLastName('')
    setLevelIds([])
    setError(null)
  }

  function close() {
    reset()
    onClose()
  }

  function toggleLevel(id, checked) {
    setLevelIds((ids) => (checked ? [...ids, id] : ids.filter((i) => i !== id)))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const created = await api.users.create({
        email: email.trim(),
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        role: 'public',
        school_level_ids: levelIds,
      })
      onCreated(created)
      reset()
      onClose()
    } catch (err) {
      setError(err?.message || 'Failed to add the user.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={close} title="Add user by email">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="invite-email" className="block text-sm font-medium text-gray-700 mb-1">
            Email
          </label>
          <input
            id="invite-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {/* Google reports the canonical form of a Gmail address, so an invite
              typed with a dot or +alias will never match the account they sign
              in with. Capitalisation is fine — addresses are normalized. */}
          <p className="mt-1 text-xs text-gray-500">
            Must be the exact address they will sign in with. A Gmail dot or
            <code className="mx-1">+alias</code> variant will not match their Google account.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="invite-first" className="block text-sm font-medium text-gray-700 mb-1">
              First name
            </label>
            <input
              id="invite-first"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label htmlFor="invite-last" className="block text-sm font-medium text-gray-700 mb-1">
              Last name
            </label>
            <input
              id="invite-last"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <fieldset>
          <legend className="block text-sm font-medium text-gray-700 mb-1">Premium access</legend>
          <div className="flex flex-wrap gap-3">
            {schoolLevels.map((sl) => (
              <label key={sl.id} className="flex items-center gap-1.5 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={levelIds.includes(sl.id)}
                  onChange={(e) => toggleLevel(sl.id, e.target.checked)}
                  aria-label={`${sl.name} premium for the new user`}
                  className="rounded border-gray-300"
                />
                {sl.name}
              </label>
            ))}
          </div>
        </fieldset>

        <ErrorBanner message={error} />

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={close}
            disabled={saving}
            className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
          >
            {saving && <Spinner size="sm" />}
            Add user
          </button>
        </div>
      </form>
    </Modal>
  )
}
