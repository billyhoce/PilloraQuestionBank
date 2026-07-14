import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

// A small "?" info button that reveals a tooltip on hover, and pins it open on
// click. The tooltip is portaled to document.body and positioned relative to the
// button (preferring above, flipping below when there's no room). Pass `label`
// for the button's aria-label and the tooltip text/markup as children.
export default function InfoTooltip({ label, children }) {
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

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        aria-label={label}
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
          {children}
        </span>,
        document.body,
      )}
    </>
  )
}
