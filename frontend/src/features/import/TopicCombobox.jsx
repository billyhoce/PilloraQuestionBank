import { useEffect, useMemo, useRef, useState } from 'react'

function flattenTopics(topics) {
  const out = []
  for (const t of topics) {
    const subtopics = t.subtopics || []
    if (subtopics.length > 0) {
      for (const s of subtopics) {
        out.push({
          key: `s-${s.id}`,
          topic_id: t.id,
          subtopic_id: s.id,
          topic_name: t.name,
          subtopic_name: s.name,
        })
      }
    } else {
      out.push({
        key: `t-${t.id}`,
        topic_id: t.id,
        subtopic_id: null,
        topic_name: t.name,
        subtopic_name: null,
      })
    }
  }
  return out
}

export default function TopicCombobox({ topics, selected, onAdd, placeholder = 'Add topic…' }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const containerRef = useRef(null)
  const inputRef = useRef(null)

  const flat = useMemo(() => flattenTopics(topics || []), [topics])
  const selectedKeys = useMemo(
    () => new Set((selected || []).map(s => `${s.topic_id}-${s.subtopic_id}`)),
    [selected]
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return flat
      .filter(opt => !selectedKeys.has(`${opt.topic_id}-${opt.subtopic_id}`))
      .filter(opt => {
        if (!q) return true
        const label = opt.subtopic_name ? `${opt.topic_name} ${opt.subtopic_name}` : opt.topic_name
        return label.toLowerCase().includes(q)
      })
      .slice(0, 50)
  }, [flat, query, selectedKeys])

  useEffect(() => { setActiveIdx(0) }, [query, open])

  useEffect(() => {
    function onDocClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function pick(opt) {
    onAdd({ topic_id: opt.topic_id, subtopic_id: opt.subtopic_id })
    setQuery('')
    setOpen(false)
    inputRef.current?.focus()
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActiveIdx(i => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filtered[activeIdx]) pick(filtered[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-sm">
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded px-2 py-1 text-sm focus:outline-none focus:border-blue-400"
      />
      {open && filtered.length > 0 && (
        <ul className="absolute z-10 left-0 right-0 mt-1 bg-white border border-gray-200 rounded shadow-md max-h-60 overflow-auto text-sm">
          {filtered.map((opt, i) => (
            <li
              key={opt.key}
              onMouseDown={(e) => { e.preventDefault(); pick(opt) }}
              onMouseEnter={() => setActiveIdx(i)}
              className={`px-2 py-1 cursor-pointer ${i === activeIdx ? 'bg-blue-50' : ''}`}
            >
              <span className="text-gray-900">{opt.topic_name}</span>
              {opt.subtopic_name && <span className="text-gray-500"> &raquo; {opt.subtopic_name}</span>}
            </li>
          ))}
        </ul>
      )}
      {open && filtered.length === 0 && query.trim() && (
        <div className="absolute z-10 left-0 right-0 mt-1 bg-white border border-gray-200 rounded shadow-md px-2 py-1 text-sm text-gray-500">
          No matches
        </div>
      )}
    </div>
  )
}
