export default function TopicMultiSelect({ topics, selectedIds, exclusive, onChange }) {
  const selectedSet = new Set(selectedIds)

  function toggle(id) {
    const next = new Set(selectedSet)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange({ topic_ids: [...next] })
  }

  function clearAll() {
    onChange({ topic_ids: [] })
  }

  return (
    <div className="flex items-start gap-3 flex-wrap">
      <div className="flex items-center flex-wrap gap-2">
        <button
          type="button"
          onClick={clearAll}
          className={`px-3 py-1 text-sm rounded-full border transition-colors ${
            selectedSet.size === 0
              ? 'bg-blue-600 text-white border-blue-600'
              : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
          }`}
        >
          All
        </button>
        {topics.map(t => {
          const active = selectedSet.has(t.id)
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => toggle(t.id)}
              className={`px-3 py-1 text-sm rounded-full border transition-colors ${
                active
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
              }`}
            >
              {t.name}
            </button>
          )
        })}
      </div>
      <label className="flex items-center gap-2 text-sm text-gray-700 whitespace-nowrap ml-auto pt-1">
        <input
          type="checkbox"
          checked={exclusive}
          disabled={selectedSet.size === 0}
          onChange={e => onChange({ exclusive: e.target.checked })}
          className="rounded border-gray-300"
        />
        Exclusive only
      </label>
    </div>
  )
}
