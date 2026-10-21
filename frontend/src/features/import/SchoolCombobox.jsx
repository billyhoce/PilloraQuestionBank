import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { closestSchools } from './schoolSuggestions'

/**
 * The school picker of the review page: type to search the existing schools.
 *   schools       - [{ id, name }]
 *   value         - the chosen school id, or null
 *   onChange      - (id | null) => void
 *   extractedName - the name the cover was read as; while no school is chosen it is shown in amber
 *                   as "<name> — not in the list", and the closest schools are listed first
 *   onNewSchool   - (name) => void; when given, the list ends with 'Use "<typed>" as a new school'
 *                   (unless the typed name is an existing school's, in any case)
 *   newName       - the new school's name once chosen that way (value is then null)
 *   label, listLabel - its label and its list's; without the school-only props it is a plain
 *                   type-to-search picker of any reference list (the Match dialog's other fields)
 */
export default function SchoolCombobox({
  schools, value, onChange, extractedName = null, onNewSchool = null, newName = null, label = 'School', listLabel = 'Schools',
}) {
  const chosen = schools.find(s => s.id === value) ?? null
  // The text being typed; null while not editing, when the input shows the chosen school.
  const [query, setQuery] = useState(null)
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const containerRef = useRef(null)
  const listId = useId()
  const unresolved = extractedName && !chosen && !newName

  const options = useMemo(() => {
    const typed = (query ?? '').trim()
    const q = typed.toLowerCase()
    if (!q) return (unresolved ? closestSchools(extractedName, schools) : schools).slice(0, 50)
    const found = schools.filter(s => s.name.toLowerCase().includes(q))
    const exact = found.find(s => s.name.toLowerCase() === q)
    // An existing name (any case) is that school, listed first; anything else may be a new school.
    const list = (exact ? [exact, ...found.filter(s => s !== exact)] : found).slice(0, 50)
    return onNewSchool && !exact ? [...list, { id: null, name: typed, isNew: true }] : list
  }, [schools, query, unresolved, extractedName, onNewSchool])

  useEffect(() => {
    function onDocClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) close()
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function close() {
    setOpen(false)
    setQuery(null)
  }

  function openList() {
    setOpen(true)
    setActiveIdx(0)
  }

  function pick(school) {
    if (school.isNew) onNewSchool(school.name)
    else onChange(school.id)
    close()
  }

  function onType(text) {
    setQuery(text)
    openList()
    if (text.trim() === '' && (value != null || newName)) onChange(null)
  }

  function onKeyDown(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) return openList()
      setActiveIdx(i => Math.min(i + 1, options.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (open && options[activeIdx]) pick(options[activeIdx])
    } else if (e.key === 'Escape') {
      close()
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <label htmlFor={`${listId}-input`} className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <input
        id={`${listId}-input`}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        value={query ?? chosen?.name ?? newName ?? ''}
        onChange={e => onType(e.target.value)}
        onFocus={openList}
        onBlur={() => setQuery(null)}
        onKeyDown={onKeyDown}
        placeholder="Type to search…"
        className={`w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
          unresolved ? 'border-amber-400 bg-amber-50' : 'border-gray-300'
        }`}
      />
      {newName && !chosen && (
        <p className="mt-1 text-xs text-blue-800">New school — created when you confirm</p>
      )}
      {unresolved && (
        <p className="mt-1 text-xs text-amber-800">
          <em>{extractedName}</em> — not in the list
        </p>
      )}
      {open && (
        <ul id={listId} role="listbox" aria-label={listLabel}
          className="absolute z-10 left-0 right-0 mt-1 bg-white border border-gray-200 rounded shadow-md max-h-60 overflow-auto text-sm">
          {options.map((s, i) => (
            <li
              key={s.isNew ? 'new' : s.id}
              role="option"
              aria-selected={!s.isNew && s.id === value}
              onMouseDown={e => { e.preventDefault(); pick(s) }}
              onMouseEnter={() => setActiveIdx(i)}
              className={`px-2 py-1 cursor-pointer ${i === activeIdx ? 'bg-blue-50' : ''}`}
            >
              {s.isNew ? `Use “${s.name}” as a new school` : s.name}
            </li>
          ))}
          {options.length === 0 && <li className="px-2 py-1 text-gray-500">No matches</li>}
        </ul>
      )}
    </div>
  )
}
