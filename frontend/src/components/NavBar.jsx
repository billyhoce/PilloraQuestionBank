import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import UserMenu from './UserMenu'

const baseLinks = [
  { to: '/', label: 'Question Bank' },
  { to: '/generate', label: 'Generate Paper' },
]

const adminLinks = [
  { to: '/admin/reference', label: 'Reference' },
  { to: '/admin/import', label: 'Import' },
  { to: '/admin/papers', label: 'Papers' },
  { to: '/admin/users', label: 'User Management' },
  { to: '/admin/generation-config', label: 'Generation Config' },
]

// Single role-aware menubar: everyone sees the base links; admins also see the
// admin links. Right side holds the account dropdown (or Log in when signed out).
export default function NavBar() {
  const { user } = useAuth()
  const location = useLocation()

  const links = user?.role === 'admin' ? [...baseLinks, ...adminLinks] : baseLinks

  // How many premium groups exist at all — needed to tell "holds some" from
  // "holds everything". Only fetched for the users the chip can apply to.
  const [schoolLevelCount, setSchoolLevelCount] = useState(null)
  const upsellApplies = !!user && user.role !== 'admin'
  useEffect(() => {
    if (!upsellApplies) return
    let cancelled = false
    api.schoolLevels.list()
      .then((data) => { if (!cancelled) setSchoolLevelCount((data || []).length) })
      .catch(() => {})  // the chip is an upsell, not a feature — stay quiet on failure
    return () => { cancelled = true }
  }, [upsellApplies])

  // Show the upsell to anyone whose premium access is incomplete. A user holding
  // nothing qualifies without waiting on the fetch; a partially-subscribed one
  // needs the total to know they're missing something.
  const held = (user?.premium_school_levels || []).length
  const showUpsell =
    upsellApplies && (held === 0 || (schoolLevelCount !== null && held < schoolLevelCount))

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <Link to="/" className="text-lg font-semibold text-gray-900">PilloraQuestionBank</Link>
        <nav className="flex items-center gap-1">
          {links.map(({ to, label }) => {
            const active =
              location.pathname === to ||
              (to !== '/' && location.pathname.startsWith(`${to}/`))
            return (
              <Link
                key={to}
                to={to}
                className={`px-3 py-1.5 rounded text-sm transition-colors ${
                  active
                    ? 'bg-gray-100 text-gray-900 font-medium'
                    : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
                }`}
              >
                {label}
              </Link>
            )
          })}
        </nav>
      </div>
      <div className="flex items-center gap-4">
        {showUpsell && (
          <Link
            to="/subscribe"
            className="text-sm font-medium px-3 py-1.5 rounded border border-amber-400 text-amber-800 bg-amber-50 hover:bg-amber-100 transition-colors"
          >
            ⭐ Go Premium
          </Link>
        )}
        {user ? (
          <UserMenu />
        ) : (
          <Link to="/login" className="text-sm text-blue-600 hover:underline">Log in</Link>
        )}
      </div>
    </header>
  )
}
