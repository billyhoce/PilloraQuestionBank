import { useRef, useState } from 'react'
import { pdfsFromDataTransfer, pdfsFromFileList } from './collectPdfs'

// The auto-import drop target. It never locks while uploads run: dropping or picking more just
// adds them to the queue. Takes loose PDFs, whole folders (dropped, or picked with "Choose
// folder"), and reports what it found through onFiles({ pdfs, ignored }).
export default function PdfDropZone({ onFiles }) {
  const fileRef = useRef(null)
  const folderRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0) // dragenter/leave fire for every child; only the outermost leave counts

  async function onDrop(e) {
    e.preventDefault()
    depth.current = 0
    setDragging(false)
    onFiles(await pdfsFromDataTransfer(e.dataTransfer))
  }

  function onPicked(e) {
    onFiles(pdfsFromFileList(e.target.files))
    e.target.value = ''
  }

  const button = 'px-3 py-1.5 rounded border text-sm font-medium bg-white hover:bg-gray-50 border-gray-300 text-gray-700'
  return (
    <div
      data-testid="pdf-drop-zone"
      data-dragging={dragging || undefined}
      onDragEnter={e => { e.preventDefault(); depth.current += 1; setDragging(true) }}
      onDragOver={e => e.preventDefault()}
      onDragLeave={() => { depth.current = Math.max(0, depth.current - 1); if (depth.current === 0) setDragging(false) }}
      onDrop={onDrop}
      className={`w-full border-2 border-dashed rounded-xl px-6 py-6 flex flex-col sm:flex-row items-center gap-4 transition-colors ${
        dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white'
      }`}
    >
      <div className="w-12 h-12 shrink-0 rounded-full bg-gray-100 flex items-center justify-center" aria-hidden="true">
        <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" />
        </svg>
      </div>
      <div className="flex-1 text-center sm:text-left">
        <p className="text-sm font-medium text-gray-800">Drop PDFs or folders of PDFs here</p>
        <p className="text-xs text-gray-500">
          Each PDF becomes its own import job. Keep adding files while earlier ones upload.
        </p>
      </div>
      <div className="flex gap-2">
        <button type="button" className={button} onClick={() => fileRef.current?.click()}>Choose files</button>
        <button type="button" className={button} onClick={() => folderRef.current?.click()}>Choose folder</button>
      </div>
      <input
        ref={fileRef}
        data-testid="pick-files"
        type="file"
        accept=".pdf,application/pdf"
        multiple
        className="hidden"
        onChange={onPicked}
      />
      <input
        ref={folderRef}
        data-testid="pick-folder"
        type="file"
        // A folder picker: React passes these through as attributes.
        webkitdirectory=""
        directory=""
        multiple
        className="hidden"
        onChange={onPicked}
      />
    </div>
  )
}
