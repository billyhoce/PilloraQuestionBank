import { useEffect } from 'react'

export default function Lightbox({ pages, currentIdx, onClose, onPrev, onNext }) {
  useEffect(() => {
    if (currentIdx === null) return
    function onKey(e) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') onPrev()
      if (e.key === 'ArrowRight') onNext()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [currentIdx, onClose, onPrev, onNext])

  if (currentIdx === null) return null

  return (
    <div
      className="fixed inset-0 bg-black/80 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="relative flex items-center gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onPrev}
          disabled={currentIdx === 0}
          className="text-white text-4xl px-3 py-2 disabled:opacity-30 hover:text-gray-300"
        >
          ‹
        </button>
        <img
          src={pages[currentIdx]?.url}
          alt={`Page ${currentIdx + 1}`}
          className="max-h-[90vh] max-w-[75vw] object-contain rounded shadow-2xl"
        />
        <button
          type="button"
          onClick={onNext}
          disabled={currentIdx === pages.length - 1}
          className="text-white text-4xl px-3 py-2 disabled:opacity-30 hover:text-gray-300"
        >
          ›
        </button>
        <button
          type="button"
          onClick={onClose}
          className="absolute -top-3 -right-3 text-white bg-black/60 rounded-full w-8 h-8 flex items-center justify-center hover:bg-black/80 text-lg leading-none"
        >
          ×
        </button>
      </div>
    </div>
  )
}
