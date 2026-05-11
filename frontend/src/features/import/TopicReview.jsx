import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import Spinner from '../../components/Spinner'
import ErrorBanner from '../../components/ErrorBanner'

export default function TopicReview({ paperId, onDone }) {
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  const run = useCallback(() => {
    setStatus('loading')
    setError(null)
    api.import.aiTopics(paperId)
      .then(() => setStatus('success'))
      .catch((e) => { setStatus('error'); setError(e.message) })
  }, [paperId])

  useEffect(() => { run() }, [run])

  if (status === 'loading') {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4">
        <Spinner size="lg" />
        <p className="text-sm text-gray-600">AI is labeling topics…</p>
        <p className="text-xs text-gray-400">This may take 10–30 seconds</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4">
        <ErrorBanner message={error} />
        <button
          type="button"
          onClick={run}
          className="border border-gray-300 rounded px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[50vh] gap-4">
      <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
        <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <p className="text-lg font-semibold text-gray-900">Topics labeled successfully!</p>
      <button
        type="button"
        onClick={onDone}
        className="bg-blue-600 hover:bg-blue-700 text-white rounded px-6 py-2 text-sm font-medium"
      >
        Done
      </button>
    </div>
  )
}
