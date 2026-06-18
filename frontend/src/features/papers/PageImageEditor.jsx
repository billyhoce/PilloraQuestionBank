import { useRef, useState } from 'react'
import { api } from '../../api/client'
import ConfirmDialog from '../../components/ConfirmDialog'

let _uidCounter = 0
function nextUid() {
  _uidCounter += 1
  return `new-${_uidCounter}`
}

// Builds a page draft from an uploaded image response.
export function newPageDraft(pageType, uploaded) {
  return {
    uid: nextUid(),
    id: null,
    temp_key: uploaded.temp_key,
    page_type: pageType,
    url: uploaded.url,
    width_px: uploaded.dimensions.width,
    height_px: uploaded.dimensions.height,
  }
}

// Builds a page draft from an existing (saved) page.
export function existingPageDraft(page) {
  return {
    uid: `p-${page.id}`,
    id: page.id,
    temp_key: null,
    page_type: page.page_type,
    url: page.url,
    width_px: page.width_px,
    height_px: page.height_px,
  }
}

export default function PageImageEditor({ label, pageType, pages, onChange, onExpand }) {
  const addInputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirmUid, setConfirmUid] = useState(null)
  const [dragIdx, setDragIdx] = useState(null)
  const [overIdx, setOverIdx] = useState(null)

  async function handleAdd(file) {
    setError(null)
    setBusy(true)
    try {
      const uploaded = await api.papers.uploadImage(file)
      onChange([...pages, newPageDraft(pageType, uploaded)])
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function handleDelete(uid) {
    onChange(pages.filter((p) => p.uid !== uid))
    setConfirmUid(null)
  }

  function handleDrop(dropIdx) {
    if (dragIdx === null || dragIdx === dropIdx) return
    const next = [...pages]
    const [moved] = next.splice(dragIdx, 1)
    next.splice(dropIdx, 0, moved)
    onChange(next)
  }

  const confirmIndex = pages.findIndex((p) => p.uid === confirmUid)

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
        <button
          type="button"
          onClick={() => addInputRef.current?.click()}
          disabled={busy}
          className="text-xs px-2 py-1 rounded border border-gray-300 hover:border-blue-400 disabled:opacity-50"
        >
          {busy ? 'Uploading…' : '+ Add page'}
        </button>
        <input
          ref={addInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => { if (e.target.files[0]) handleAdd(e.target.files[0]); e.target.value = '' }}
        />
      </div>

      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}

      {pages.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No {pageType} pages</p>
      ) : (
        <div className="flex flex-col gap-2 max-h-96 overflow-y-auto pr-1">
          {pages.map((p, i) => (
            <div
              key={p.uid}
              draggable
              onDragStart={() => setDragIdx(i)}
              onDragEnd={() => { setDragIdx(null); setOverIdx(null) }}
              onDragOver={(e) => { e.preventDefault(); if (overIdx !== i) setOverIdx(i) }}
              onDrop={(e) => { e.preventDefault(); handleDrop(i); setOverIdx(null) }}
              className={`group relative w-full overflow-hidden rounded border-2 bg-gray-50 cursor-grab active:cursor-grabbing transition-colors ${
                overIdx === i && dragIdx !== null ? 'border-blue-400 ring-2 ring-blue-300' : 'border-gray-300'
              } ${dragIdx === i ? 'opacity-40' : ''}`}
            >
              <img
                src={p.url}
                alt={`${pageType} page ${i + 1}`}
                onClick={() => onExpand(p.url)}
                className="w-full h-auto object-contain select-none"
                draggable={false}
              />
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setConfirmUid(p.uid) }}
                className="absolute top-1 right-1 hidden group-hover:flex items-center justify-center w-6 h-6 rounded-full bg-black/60 hover:bg-red-600 text-white text-sm leading-none"
                aria-label={`Delete ${pageType} page ${i + 1}`}
              >×</button>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        isOpen={confirmUid !== null}
        onClose={() => setConfirmUid(null)}
        onConfirm={() => handleDelete(confirmUid)}
        itemName={confirmIndex >= 0 ? `${pageType} page ${confirmIndex + 1}` : 'this page'}
      />
    </div>
  )
}
