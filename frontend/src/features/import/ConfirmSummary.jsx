import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'

function MetaLine({ label, value }) {
  return (
    <div>
      <span className="font-medium">{label}:</span> {value ?? '—'}
    </div>
  )
}

function lookupName(refs, listKey, id) {
  return refs?.[listKey]?.find((x) => x.id === id)?.name ?? '—'
}

export default function ConfirmSummary({
  questions, metadata, refs, marksMap, onMarksChange, onConfirm, onBack, onCancel, loading, error,
}) {
  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Review &amp; Confirm</h2>
      <ErrorBanner message={error} />
      <div className="overflow-x-auto mb-6">
        <table className="w-full text-sm border border-gray-200 rounded">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-12">Q#</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Question pages</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Answer pages</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-24">Marks</th>
            </tr>
          </thead>
          <tbody>
            {questions.map((q) => (
              <tr key={q.question_number} className="border-t border-gray-200">
                <td className="px-4 py-2 font-medium">Q{q.question_number}</td>
                <td className="px-4 py-2">{q.pages.filter((p) => p.page_type === 'question').length}</td>
                <td className="px-4 py-2">{q.pages.filter((p) => p.page_type === 'answer').length}</td>
                <td className="px-4 py-2">
                  <input
                    type="number"
                    min="0"
                    value={marksMap[q.question_number] ?? ''}
                    onChange={(e) =>
                      onMarksChange(q.question_number, e.target.value !== '' ? Number(e.target.value) : null)
                    }
                    placeholder="—"
                    className="w-16 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-gray-50 rounded border border-gray-200 px-4 py-3 text-sm text-gray-700 mb-6 space-y-1">
        <MetaLine label="Subject" value={lookupName(refs, 'subjects', metadata.subject_id)} />
        <MetaLine label="Stream" value={lookupName(refs, 'streams', metadata.stream_id)} />
        <MetaLine label="Level" value={lookupName(refs, 'levels', metadata.level_id)} />
        <MetaLine label="School" value={lookupName(refs, 'schools', metadata.school_id)} />
        <MetaLine label="Exam Type" value={lookupName(refs, 'examTypes', metadata.exam_type_id)} />
        <MetaLine label="Year" value={metadata.year} />
        <MetaLine label="Paper" value={metadata.paper_number} />
      </div>

      <div className="flex justify-between items-center">
        <button
          type="button"
          onClick={onBack}
          disabled={loading}
          className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          ← Back
        </button>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="text-sm text-red-600 hover:text-red-700 disabled:opacity-50"
          >
            Cancel Import
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded px-4 py-2 text-sm font-medium flex items-center gap-2"
          >
            {loading && <Spinner size="sm" />}
            Confirm &amp; Import
          </button>
        </div>
      </div>
    </div>
  )
}
