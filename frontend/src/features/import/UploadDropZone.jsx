import { useRef, useState } from 'react'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'

export default function UploadDropZone({ onUpload, loading, error, loadingMessage }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function handleFiles(fileList) {
    const pdfs = Array.from(fileList).filter(f => f.type === 'application/pdf')
    if (pdfs.length === 0) return
    onUpload(pdfs)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh]">
      <div
        className={`w-full max-w-lg border-2 border-dashed rounded-xl p-12 flex flex-col items-center gap-4 cursor-pointer transition-colors ${
          dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-white hover:border-blue-400'
        } ${loading ? 'pointer-events-none' : ''}`}
        onClick={() => !loading && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          className="hidden"
          onChange={(e) => { handleFiles(e.target.files); e.target.value = '' }}
        />
        {loading ? (
          <>
            <Spinner size="lg" />
            <p className="text-sm text-gray-600">{loadingMessage || 'Converting PDF pages…'}</p>
          </>
        ) : (
          <>
            <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center">
              <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <p className="text-base font-medium text-gray-700">Drag &amp; drop PDF(s) here</p>
            <p className="text-sm text-gray-400">or click to browse</p>
          </>
        )}
      </div>
      <div className="mt-4 w-full max-w-lg">
        <ErrorBanner message={error} />
      </div>
    </div>
  )
}
