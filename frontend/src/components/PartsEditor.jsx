import TopicCombobox from '../features/import/TopicCombobox'
import { emptyPart, partsTotalMarks } from '../features/import/topicUtils'
import { formatTopic } from '../utils/topicFormat'

/**
 * Edits a question's parts — label, marks, and topics per part.
 *
 * Used by both the import topic-review step and the admin question editor, which
 * previously carried near-identical copies of the topic chip + combobox block.
 * `parts` is the editor shape from topicUtils (`{label, marks, selected}`);
 * `onChange` receives the whole replacement array.
 */
export default function PartsEditor({ parts, topics, lookup, onChange, disabled = false }) {
  const { subtopicById, topicById } = lookup || {}
  const total = partsTotalMarks(parts)

  function updatePart(idx, patch) {
    onChange(parts.map((p, i) => (i === idx ? { ...p, ...patch } : p)))
  }

  function addPart() {
    onChange([...parts, emptyPart()])
  }

  function removePart(idx) {
    const next = parts.filter((_, i) => i !== idx)
    // A question always has at least one part.
    onChange(next.length > 0 ? next : [emptyPart()])
  }

  function addTopic(idx, sel) {
    const part = parts[idx]
    if (part.selected.some((s) => s.topic_id === sel.topic_id && s.subtopic_id === sel.subtopic_id)) return
    updatePart(idx, { selected: [...part.selected, sel] })
  }

  function removeTopic(idx, selIdx) {
    updatePart(idx, { selected: parts[idx].selected.filter((_, i) => i !== selIdx) })
  }

  function labelFor(sel) {
    if (sel.subtopic_id != null) {
      const s = subtopicById?.get(sel.subtopic_id)
      return s
        ? <><strong>{formatTopic(s.topic_number, s.topic_name)}</strong> &raquo; {s.name}</>
        : `Unknown subtopic ${sel.subtopic_id}`
    }
    const t = topicById?.get(sel.topic_id)
    return t ? <strong>{formatTopic(t.topic_number, t.name)}</strong> : `Unknown topic ${sel.topic_id}`
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-wide text-gray-500">Parts</p>
        <span className="text-xs text-gray-600">
          {total != null ? `Total ${total} ${total === 1 ? 'mark' : 'marks'}` : 'Total —'}
        </span>
      </div>

      {parts.map((part, idx) => (
        <div key={idx} className="border border-gray-200 rounded-lg p-3 bg-gray-50">
          <div className="flex items-center gap-2 mb-2">
            <label className="flex items-center gap-1 text-xs text-gray-600">
              Part
              <input
                type="text"
                value={part.label}
                disabled={disabled}
                onChange={(e) => updatePart(idx, { label: e.target.value })}
                placeholder="(a)"
                aria-label={`Part ${idx + 1} label`}
                className="w-20 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              />
            </label>
            <label className="flex items-center gap-1 text-xs text-gray-600">
              Marks
              <input
                type="number"
                min="0"
                value={part.marks ?? ''}
                disabled={disabled}
                onChange={(e) => updatePart(idx, { marks: e.target.value !== '' ? Number(e.target.value) : null })}
                placeholder="—"
                aria-label={`Part ${idx + 1} marks`}
                className="w-16 border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              />
            </label>
            <button
              type="button"
              onClick={() => removePart(idx)}
              disabled={disabled}
              aria-label={`Remove part ${idx + 1}`}
              className="ml-auto text-gray-400 hover:text-red-600 text-lg disabled:opacity-50"
            >
              &times;
            </button>
          </div>

          {part.selected.length === 0 && (
            <p className="text-sm text-gray-400 italic mb-2">No topics selected</p>
          )}
          {part.selected.map((sel, selIdx) => (
            <div key={selIdx} className="flex items-start gap-2 mb-2 bg-blue-50 border border-blue-200 rounded-lg p-2">
              <p className="text-sm text-gray-700 flex-grow">{labelFor(sel)}</p>
              <button
                type="button"
                onClick={() => removeTopic(idx, selIdx)}
                disabled={disabled}
                className="text-gray-400 hover:text-red-600 text-lg flex-shrink-0 mt-0.5 disabled:opacity-50"
                aria-label="Remove topic"
              >
                &times;
              </button>
            </div>
          ))}

          <TopicCombobox
            topics={topics || []}
            selected={part.selected}
            onAdd={(sel) => addTopic(idx, sel)}
          />
        </div>
      ))}

      <div>
        <button
          type="button"
          onClick={addPart}
          disabled={disabled}
          className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-700 hover:border-blue-400 disabled:opacity-50"
        >
          + Add part
        </button>
      </div>
    </div>
  )
}
