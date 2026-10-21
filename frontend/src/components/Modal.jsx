import { useEffect } from 'react'

// `wide` gives room for a list with previews (the import page's Match dialog).
export default function Modal({ isOpen, onClose, title, children, wide = false }) {
  useEffect(() => {
    if (!isOpen) return
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div role="dialog" aria-modal="true" aria-label={title}
        className={`bg-white rounded-lg shadow-xl w-full ${wide ? 'max-w-4xl max-h-[90vh] flex flex-col' : 'max-w-md'}`}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className={`px-6 py-4 ${wide ? 'overflow-y-auto' : ''}`}>{children}</div>
      </div>
    </div>
  )
}
