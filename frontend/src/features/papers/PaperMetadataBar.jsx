import { useState } from 'react'
import Modal from '../../components/Modal'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'

function SelectField({ label, value, onChange, options }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <select
        value={value ?? ''}
        onChange={onChange}
        className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        <option value="">— select —</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.name}</option>
        ))}
      </select>
    </div>
  )
}

export default function PaperMetadataBar({ metadata, refs, onSave }) {
  const [draft, setDraft] = useState(metadata)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [confirmChange, setConfirmChange] = useState(false)

  function set(key, val) {
    setDraft((prev) => ({ ...prev, [key]: val }))
  }
  function handleSelect(key) {
    return (e) => set(key, e.target.value ? Number(e.target.value) : null)
  }

  const changed =
    draft.subject_id !== metadata.subject_id || draft.stream_id !== metadata.stream_id

  const isComplete =
    draft.subject_id && draft.stream_id && draft.level_id &&
    draft.school_id && draft.exam_type_id && draft.year && draft.paper_number

  async function doSave() {
    setSaving(true)
    setError(null)
    try {
      await onSave(draft, changed)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
      setConfirmChange(false)
    }
  }

  function handleSaveClick() {
    if (changed) setConfirmChange(true)
    else doSave()
  }

  if (!refs) return null

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
      <div className="flex flex-wrap items-end gap-3">
        <SelectField label="Subject" value={draft.subject_id} onChange={handleSelect('subject_id')} options={refs.subjects} />
        <SelectField label="Stream" value={draft.stream_id} onChange={handleSelect('stream_id')} options={refs.streams} />
        <SelectField label="Level" value={draft.level_id} onChange={handleSelect('level_id')} options={refs.levels} />
        <SelectField label="School" value={draft.school_id} onChange={handleSelect('school_id')} options={refs.schools} />
        <SelectField label="Exam Type" value={draft.exam_type_id} onChange={handleSelect('exam_type_id')} options={refs.examTypes} />
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Year</label>
          <input
            type="number"
            value={draft.year}
            onChange={(e) => set('year', e.target.value)}
            className="w-24 border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Paper No.</label>
          <input
            type="text"
            value={draft.paper_number}
            onChange={(e) => set('paper_number', e.target.value)}
            className="w-20 border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-gray-700 select-none">
          <input
            type="checkbox"
            checked={!!draft.is_premium}
            onChange={(e) => set('is_premium', e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Premium paper
        </label>
        <button
          type="button"
          onClick={handleSaveClick}
          disabled={saving || !isComplete}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
        >
          {saving && <Spinner size="sm" />} Save metadata
        </button>
      </div>

      {error && <div className="mt-3"><ErrorBanner message={error} /></div>}

      <Modal isOpen={confirmChange} onClose={() => !saving && setConfirmChange(false)} title="Change subject or stream?">
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            Topics are scoped to a paper's subject and stream. Changing them will
            <strong> clear all topic labels</strong> on this paper's questions. The AI
            labeller will then suggest fresh topics for you to review and save.
          </p>
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setConfirmChange(false)}
              disabled={saving}
              className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >Cancel</button>
            <button
              onClick={doSave}
              disabled={saving}
              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
            >
              {saving && <Spinner size="sm" />} Clear topics & save
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
