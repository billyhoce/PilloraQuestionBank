import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'

function SelectField({ label, value, onChange, options }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <select
        value={value ?? ''}
        onChange={onChange}
        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        <option value="">— select —</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.name}</option>
        ))}
      </select>
    </div>
  )
}

export default function MetadataSidebar({ metadata, onChange, refs, questionCount, answerCount, onNext, onCancel, loading, error }) {
  function set(key, val) {
    onChange({ ...metadata, [key]: val })
  }

  function handleSelect(key) {
    return (e) => set(key, e.target.value ? Number(e.target.value) : null)
  }

  const isComplete =
    metadata.subject_id &&
    metadata.stream_id &&
    metadata.level_id &&
    metadata.school_id &&
    metadata.exam_type_id &&
    metadata.year &&
    metadata.paper_number

  return (
    <div className="w-52 flex-shrink-0 flex flex-col gap-3 p-4 bg-white border-l border-gray-200 overflow-y-auto">
      {!refs ? (
        <div className="flex justify-center py-4"><Spinner /></div>
      ) : (
        <>
          <SelectField label="Subject" value={metadata.subject_id} onChange={handleSelect('subject_id')} options={refs.subjects} />
          <SelectField label="Stream" value={metadata.stream_id} onChange={handleSelect('stream_id')} options={refs.streams} />
          <SelectField label="Level" value={metadata.level_id} onChange={handleSelect('level_id')} options={refs.levels} />
          <SelectField label="School" value={metadata.school_id} onChange={handleSelect('school_id')} options={refs.schools} />
          <SelectField label="Exam Type" value={metadata.exam_type_id} onChange={handleSelect('exam_type_id')} options={refs.examTypes} />
        </>
      )}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Year</label>
        <input
          type="number"
          value={metadata.year}
          onChange={(e) => set('year', e.target.value)}
          placeholder="2024"
          className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Paper No.</label>
        <input
          type="text"
          value={metadata.paper_number}
          onChange={(e) => set('paper_number', e.target.value)}
          placeholder="1"
          className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-700 select-none">
        <input
          type="checkbox"
          checked={!!metadata.is_premium}
          onChange={(e) => set('is_premium', e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        Premium paper
      </label>
      <div className="text-xs text-gray-500 pt-1 space-y-0.5">
        <div>{questionCount} question{questionCount !== 1 ? 's' : ''}</div>
        {answerCount > 0 && <div>{answerCount} answer set{answerCount !== 1 ? 's' : ''}</div>}
      </div>
      {error && <ErrorBanner message={error} />}
      <button
        type="button"
        onClick={onNext}
        disabled={!isComplete || loading}
        className="mt-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center justify-center gap-2"
      >
        {loading && <Spinner size="sm" />}
        Confirm &amp; Import →
      </button>
      <button
        type="button"
        onClick={onCancel}
        disabled={loading}
        className="text-xs text-red-600 hover:text-red-700 text-center disabled:opacity-50"
      >
        Cancel Import
      </button>
    </div>
  )
}
