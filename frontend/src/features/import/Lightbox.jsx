import { useEffect } from 'react'

export default function Lightbox({ pages, currentIdx, onClose, onPrev, onNext, canMerge, onToggleMerge }) {
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

  const page = pages[currentIdx]
  const showMerge = Boolean(onToggleMerge && canMerge?.(currentIdx))

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
        <div className="flex flex-col items-center gap-3">
          <img
            src={page?.url}
            alt={`Page ${currentIdx + 1}`}
            className="max-h-[85vh] max-w-[75vw] object-contain rounded shadow-2xl"
          />
          {showMerge && (
            <button
              type="button"
              title="Merge with previous"
              onClick={() => onToggleMerge(currentIdx)}
              className={`text-sm px-3 py-1.5 rounded border transition-colors ${
                page?.mergeWithPrev
                  ? 'bg-blue-100 text-blue-700 border-blue-300'
                  : 'bg-white/10 text-white border-white/40 hover:bg-white/20'
              }`}
            >
              Merge with prev
            </button>
          )}
        </div>
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
