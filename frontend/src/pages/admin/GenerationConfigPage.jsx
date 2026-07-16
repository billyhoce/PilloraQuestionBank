import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import SimpleTab from '../../features/reference/tabs/SimpleTab'
import CoverBodyEditor from '../../components/generate/CoverBodyEditor'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'

// Admin page for the generation presets applied to every non-admin generation:
// the cover-title list users pick from, the subtitle placeholders shown in the
// Generate form, and the cover body / header / footer stamped on their PDFs.
export default function GenerationConfigPage() {
  const [titles, setTitles] = useState([])
  const [form, setForm] = useState(null) // null until the config loads
  const [pageLoading, setPageLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState(null) // { type: 'success' | 'warning', text }

  useEffect(() => {
    api.generationConfig.get()
      .then(cfg => {
        setTitles(cfg.titles)
        setForm({
          subtitle1_placeholder: cfg.subtitle1_placeholder,
          subtitle2_placeholder: cfg.subtitle2_placeholder,
          cover_body: cfg.cover_body,
          header_text: cfg.header_text,
          footer_text: cfg.footer_text,
        })
      })
      .catch(e => setLoadError(e?.message || 'Failed to load generation config'))
      .finally(() => setPageLoading(false))
  }, [])

  async function refreshTitles() {
    setTitles(await api.coverTitles.list())
  }

  function setField(key, value) {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setNotice(null)
    try {
      const updated = await api.generationConfig.update(form)
      setTitles(updated.titles)
      setNotice({ type: 'success', text: 'Generation config saved.' })
    } catch (e) {
      setNotice({ type: 'warning', text: e?.message || 'Failed to save generation config.' })
    } finally {
      setSaving(false)
    }
  }

  if (pageLoading) {
    return (
      <div className="flex items-center justify-center py-16"><Spinner size="lg" /></div>
    )
  }

  return (
    <div className="max-w-[90%] mx-auto space-y-8">
      <h1 className="text-2xl font-semibold text-gray-900">Generation Config</h1>

      <ErrorBanner message={loadError} />

      <section className="space-y-2">
        <h2 className="text-lg font-medium text-gray-900">Cover Titles</h2>
        <p className="text-sm text-gray-500">
          Users generating a paper must pick their cover title from this list (the first entry is
          the default). Admins can also type a custom title during generation.
        </p>
        <SimpleTab
          label="Cover Title"
          rows={titles}
          loading={false}
          onCreate={async (name) => { await api.coverTitles.create(name); await refreshTitles() }}
          onUpdate={async (id, name) => { await api.coverTitles.update(id, name); await refreshTitles() }}
          onDelete={async (id) => { await api.coverTitles.delete(id); await refreshTitles() }}
        />
      </section>

      {form ? (
        <section className="space-y-4 max-w-2xl">
          <h2 className="text-lg font-medium text-gray-900">Generation Presets</h2>
          <p className="text-sm text-gray-500">
            Applied to every paper a user generates: their PDFs always include a cover page with
            this cover body, plus this header and footer. The subtitle placeholders are the grey
            hint text shown in the Generate form's subtitle fields.
          </p>

          <div className="space-y-1">
            <label className="text-sm text-gray-700" htmlFor="subtitle1-placeholder">
              Subtitle 1 placeholder
            </label>
            <input
              id="subtitle1-placeholder"
              type="text"
              value={form.subtitle1_placeholder}
              onChange={e => setField('subtitle1_placeholder', e.target.value)}
              placeholder="e.g. Secondary 3 Mathematics"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm text-gray-700" htmlFor="subtitle2-placeholder">
              Subtitle 2 placeholder
            </label>
            <input
              id="subtitle2-placeholder"
              type="text"
              value={form.subtitle2_placeholder}
              onChange={e => setField('subtitle2_placeholder', e.target.value)}
              placeholder="e.g. 2024 Prelim"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            />
          </div>

          <div className="space-y-1">
            <span className="text-sm text-gray-700">Cover body</span>
            <CoverBodyEditor
              value={form.cover_body}
              onChange={value => setField('cover_body', value)}
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm text-gray-700" htmlFor="config-header-text">
              Header / instructions
            </label>
            <textarea
              id="config-header-text"
              rows={2}
              value={form.header_text}
              onChange={e => setField('header_text', e.target.value)}
              placeholder="e.g. Answer all questions. Time: 2 hours."
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm resize-y"
            />
          </div>

          <div className="space-y-1">
            <label className="text-sm text-gray-700" htmlFor="config-footer-text">
              Footer
            </label>
            <input
              id="config-footer-text"
              type="text"
              value={form.footer_text}
              onChange={e => setField('footer_text', e.target.value)}
              placeholder="Shown at the bottom of every page"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            />
          </div>

          {notice ? (
            <div
              className={`text-sm rounded px-3 py-2 ${
                notice.type === 'success'
                  ? 'bg-green-50 text-green-700 border border-green-200'
                  : 'bg-amber-50 text-amber-800 border border-amber-200'
              }`}
            >
              {notice.text}
            </div>
          ) : null}

          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {saving ? <Spinner size="sm" /> : null}
            {saving ? 'Saving…' : 'Save Presets'}
          </button>
        </section>
      ) : null}
    </div>
  )
}
