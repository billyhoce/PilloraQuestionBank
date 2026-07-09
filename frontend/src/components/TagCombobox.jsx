import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * Flat searchable typeahead for tags. Mirrors the topic TopicCombobox but tags
 * are flat (just id + name). Props:
 *   tags        - [{ id, name }]
 *   selectedIds - array of already-selected tag ids (excluded from options)
 *   onAdd       - (tag) => void, called with the picked { id, name }
 *   placeholder - input placeholder
 */
export default function TagCombobox({ tags, selectedIds, onAdd, placeholder = 'Add tag…' }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const containerRef = useRef(null)
  const inputRef = useRef(null)

  const selectedSet = useMemo(() => new Set(selectedIds || []), [selectedIds])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (tags || [])
      .filter(t => !selectedSet.has(t.id))
      .filter(t => !q || t.name.toLowerCase().includes(q))
      .slice(0, 50)
  }, [tags, query, selectedSet])

  useEffect(() => { setActiveIdx(0) }, [query, open])

  useEffect(() => {
    function onDocClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function pick(tag) {
    onAdd(tag)
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
          {filtered.map((tag, i) => (
            <li
              key={tag.id}
              onMouseDown={(e) => { e.preventDefault(); pick(tag) }}
              onMouseEnter={() => setActiveIdx(i)}
              className={`px-2 py-1 cursor-pointer ${i === activeIdx ? 'bg-blue-50' : ''}`}
            >
              <span className="text-gray-900">{tag.name}</span>
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
