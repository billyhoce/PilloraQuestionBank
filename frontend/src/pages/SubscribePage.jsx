import { useAuth } from '../context/AuthContext'

const PERKS = [
  'Access to every premium exam paper',
  'View premium question images in full',
  'Generate custom papers using premium questions',
]

// Stubbed subscribe page. Payment is not implemented yet — the button is a
// visual placeholder and premium access is granted by an admin via User
// Management until the payment flow is built.
export default function SubscribePage() {
  const { user } = useAuth()
  const isPremium = user?.role === 'premium' || user?.role === 'admin'

  return (
    <div className="max-w-lg mx-auto py-10 px-4">
      <div className="bg-white border border-gray-200 rounded-xl p-8 shadow-sm">
        <div className="text-center">
          <div className="text-3xl mb-2" aria-hidden="true">⭐</div>
          <h1 className="text-2xl font-semibold text-gray-900">Pillora Premium</h1>
          <p className="text-sm text-gray-500 mt-1">Unlock the full question bank.</p>
        </div>

        <div className="my-6 text-center">
          <span className="text-4xl font-bold text-gray-900">$9.90</span>
          <span className="text-sm text-gray-500"> / month</span>
        </div>

        <ul className="space-y-2 mb-8">
          {PERKS.map((perk) => (
            <li key={perk} className="flex items-start gap-2 text-sm text-gray-700">
              <span className="text-green-600 mt-0.5" aria-hidden="true">✓</span>
              {perk}
            </li>
          ))}
        </ul>

        {isPremium ? (
          <div className="rounded-lg bg-green-50 border border-green-200 text-green-800 text-sm text-center py-3 px-4">
            You already have premium access. Enjoy!
          </div>
        ) : (
          <>
            <button
              type="button"
              disabled
              title="Payments are coming soon"
              className="w-full bg-blue-600 text-white rounded-lg py-2.5 text-sm font-medium opacity-60 cursor-not-allowed"
            >
              Subscribe
            </button>
            <p className="text-xs text-gray-400 text-center mt-3">
              Payments are coming soon. In the meantime, ask an admin to grant you
              premium access.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
