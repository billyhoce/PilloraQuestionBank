import { useState } from 'react'
import ManualImport from './ManualImport'
import AutoImport from './AutoImport'

// The Manual flow keeps its in-progress step in sessionStorage; if one exists,
// reopen on Manual so a reload doesn't strand it behind the Auto-detect tab.
const MANUAL_SESSION_KEY = 'pillora_import_session'

function manualInProgress() {
  try {
    return sessionStorage.getItem(MANUAL_SESSION_KEY) !== null
  } catch {
    return false
  }
}

const MODES = [
  { id: 'auto', label: 'Auto-detect' },
  { id: 'manual', label: 'Manual' },
]

export default function ImportPage() {
  const [mode, setMode] = useState(() => (manualInProgress() ? 'manual' : 'auto'))

  return (
    <div>
      <div role="tablist" aria-label="Import mode" className="flex gap-1 px-4 pt-3 border-b border-gray-200">
        {MODES.map(m => (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={mode === m.id}
            onClick={() => setMode(m.id)}
            className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 ${
              mode === m.id
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      {mode === 'auto' ? <AutoImport /> : <ManualImport />}
    </div>
  )
}
