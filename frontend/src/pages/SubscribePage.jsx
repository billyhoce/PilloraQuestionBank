import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { hasSchoolLevel } from '../utils/premium'
import Spinner from '../components/Spinner'
import ErrorBanner from '../components/ErrorBanner'

const perksFor = (schoolLevelName) => [
  `Access to every premium ${schoolLevelName} exam paper`,
  'View premium question images in full',
  'Generate custom papers using premium questions',
]

// Stubbed subscribe page. Payment is not implemented yet — the buttons are
// visual placeholders and premium access is granted by an admin via User
// Management until the payment flow is built.
//
// Premium is sold per school level, so there is one plan per school level rather
// than one product. A locked question links here with ?school_level=<name> so the
// plan the viewer actually needs is the one highlighted.
export default function SubscribePage() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const highlighted = searchParams.get('school_level')

  const [schoolLevels, setSchoolLevels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.schoolLevels.list()
      .then((data) => { setSchoolLevels(data || []); setError(null) })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="flex justify-center py-12"><Spinner size="lg" /></div>
  }

  return (
    <div className="max-w-4xl mx-auto py-10 px-4">
      <div className="text-center mb-8">
        <div className="text-3xl mb-2" aria-hidden="true">⭐</div>
        <h1 className="text-2xl font-semibold text-gray-900">Pillora Premium</h1>
        <p className="text-sm text-gray-500 mt-1">
          Unlock the full question bank — one plan per school level.
        </p>
      </div>

      {error && <div className="mb-4"><ErrorBanner message={error} /></div>}

      <div className="grid gap-6 sm:grid-cols-2">
        {schoolLevels.map((sl) => {
          const owned = hasSchoolLevel(user, sl.name)
          const isHighlighted = highlighted === sl.name
          return (
            <div
              key={sl.id}
              data-testid={`plan-${sl.name}`}
              className={`bg-white border rounded-xl p-6 shadow-sm ${
                isHighlighted ? 'border-amber-400 ring-2 ring-amber-200' : 'border-gray-200'
              }`}
            >
              <h2 className="text-lg font-semibold text-gray-900">{sl.name} Premium</h2>
              {isHighlighted && !owned && (
                <p className="text-xs text-amber-700 mt-1">
                  This is the plan the question you opened needs.
                </p>
              )}

              <div className="my-5">
                <span className="text-3xl font-bold text-gray-900">$9.90</span>
                <span className="text-sm text-gray-500"> / month</span>
              </div>

              <ul className="space-y-2 mb-6">
                {perksFor(sl.name).map((perk) => (
                  <li key={perk} className="flex items-start gap-2 text-sm text-gray-700">
                    <span className="text-green-600 mt-0.5" aria-hidden="true">✓</span>
                    {perk}
                  </li>
                ))}
              </ul>

              {owned ? (
                <div className="rounded-lg bg-green-50 border border-green-200 text-green-800 text-sm text-center py-2.5 px-4">
                  You already have {sl.name} access. Enjoy!
                </div>
              ) : (
                <button
                  type="button"
                  disabled
                  title="Payments are coming soon"
                  className="w-full bg-blue-600 text-white rounded-lg py-2.5 text-sm font-medium opacity-60 cursor-not-allowed"
                >
                  Subscribe to {sl.name}
                </button>
              )}
            </div>
          )
        })}
      </div>

      <p className="text-xs text-gray-400 text-center mt-6">
        Payments are coming soon. In the meantime, ask an admin to grant you premium access.
      </p>
    </div>
  )
}
