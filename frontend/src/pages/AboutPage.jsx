import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useSiteConfig } from '../context/SiteConfigContext'
import RichContentEditor from '../components/RichContentEditor'
import Spinner from '../components/Spinner'

// Public page whose body is admin-authored rich text. Editing happens **in
// place** rather than on a separate admin page: the editor surface and the
// rendered page share the `.rich-content` class, so what the admin sees while
// typing is exactly what visitors get.
//
// The HTML is sanitized server-side on write (app/services/site_config.py), so
// what arrives here has already been through the allowlist — dangerouslySetInnerHTML
// is safe, and there is no client-side sanitizer to keep in sync.
export default function AboutPage() {
  const { user } = useAuth()
  const { aboutContent, loading, setConfig } = useSiteConfig()
  const isAdmin = user?.role === 'admin'

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState(null) // { type: 'success' | 'warning', text }

  // The draft is seeded when editing starts rather than kept in sync by an
  // effect — outside the editor it is unused, and syncing it would risk
  // clobbering unsaved typing if the config were ever refetched mid-edit.
  function startEditing() {
    setDraft(aboutContent)
    setNotice(null)
    setEditing(true)
  }

  async function handleSave() {
    setSaving(true)
    setNotice(null)
    try {
      // The server returns the *sanitized* HTML, so store what came back rather
      // than the draft — otherwise the page would briefly show markup that was
      // stripped on write.
      const updated = await api.siteConfig.update({ about_content: draft })
      setConfig(updated)
      setEditing(false)
      setNotice({ type: 'success', text: 'About page saved.' })
    } catch (e) {
      setNotice({ type: 'warning', text: e?.message || 'Failed to save the About page.' })
    } finally {
      setSaving(false)
    }
  }

  function handleCancel() {
    setEditing(false)
    setNotice(null)
  }

  if (loading) {
    return <div className="flex items-center justify-center py-16"><Spinner size="lg" /></div>
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-gray-900">About</h1>
        {isAdmin && !editing && (
          <button
            type="button"
            onClick={startEditing}
            className="text-sm font-medium px-3 py-1.5 rounded border border-blue-500 text-blue-600 hover:bg-blue-50 transition-colors"
          >
            Edit page
          </button>
        )}
      </div>

      {notice && (
        <div
          role="status"
          className={`text-sm px-3 py-2 rounded border ${
            notice.type === 'success'
              ? 'bg-green-50 border-green-300 text-green-800'
              : 'bg-amber-50 border-amber-300 text-amber-800'
          }`}
        >
          {notice.text}
        </div>
      )}

      {isAdmin && editing ? (
        <div className="space-y-3">
          <RichContentEditor
            value={draft}
            onChange={setDraft}
            label="About page content"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="text-sm font-medium px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              disabled={saving}
              className="text-sm px-4 py-1.5 rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg p-6">
          {aboutContent ? (
            <div className="rich-content text-gray-800" dangerouslySetInnerHTML={{ __html: aboutContent }} />
          ) : (
            <p className="text-sm text-gray-500">Nothing here yet.</p>
          )}
        </div>
      )}
    </div>
  )
}
