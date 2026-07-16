import { Link, useLocation } from 'react-router-dom'
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
        {user?.role === 'public' && (
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
