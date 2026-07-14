import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { formatTopic } from '../../utils/topicFormat'

export default function TopicMultiSelect({ topics, selectedIds, exclusive, onChange }) {
  const selectedSet = new Set(selectedIds)
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState(null)
  const btnRef = useRef(null)
  const tipRef = useRef(null)
  const pinnedRef = useRef(false)

  function close() {
    pinnedRef.current = false
    setOpen(false)
    setCoords(null)
  }

  // Position the tooltip relative to the button, preferring above and flipping
  // below when there isn't room; clamp horizontally into the viewport. Runs
  // before paint so there's no flicker.
  useLayoutEffect(() => {
    if (!open || !btnRef.current || !tipRef.current) return
    const b = btnRef.current.getBoundingClientRect()
    const t = tipRef.current.getBoundingClientRect()
    const gap = 8
    const margin = 8
    let top = b.top - t.height - gap
    if (top < margin) top = b.bottom + gap
    let left = b.left + b.width / 2 - t.width / 2
    left = Math.max(margin, Math.min(left, window.innerWidth - t.width - margin))
    setCoords({ top, left })
  }, [open])

  // Dismiss on outside click, Escape, or scroll/resize while open.
  useEffect(() => {
    if (!open) return
    function onMouseDown(e) {
      if (btnRef.current?.contains(e.target)) return
      if (tipRef.current?.contains(e.target)) return
      close()
    }
    function onKeyDown(e) {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

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
              {formatTopic(t.topic_number, t.name)}
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
        <button
          ref={btnRef}
          type="button"
          aria-label="What does Exclusive only do?"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => { if (!pinnedRef.current) setOpen(false) }}
          onClick={e => {
            e.preventDefault()
            e.stopPropagation()
            pinnedRef.current = !pinnedRef.current
            setOpen(pinnedRef.current)
          }}
          className="inline-flex items-center justify-center w-4 h-4 text-xs rounded-full border border-gray-400 text-gray-500 cursor-pointer"
        >
          ?
        </button>
      </label>
      {open && createPortal(
        <span
          ref={tipRef}
          role="tooltip"
          style={{
            top: coords?.top ?? 0,
            left: coords?.left ?? 0,
            width: 'max-content',
            maxWidth: 260,
            textWrap: 'balance',
            visibility: coords ? 'visible' : 'hidden',
          }}
          className="fixed z-[9999] rounded border border-gray-200 bg-white text-gray-800 text-xs font-normal px-2.5 py-1.5 shadow-lg whitespace-normal break-words"
        >
          Show only questions that cover just your selected topics and nothing else.
        </span>,
        document.body,
      )}
    </div>
  )
}
