import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const navLinks = [
  { to: '/', label: 'Question Bank' },
  { to: '/admin/reference', label: 'Reference' },
  { to: '/admin/import', label: 'Import' },
  { to: '/admin/papers', label: 'Papers' },
]

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="text-lg font-semibold text-gray-900">Pillora Admin</span>
          <nav className="flex items-center gap-1">
            {navLinks.map(({ to, label }) => {
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
          <span className="text-sm text-gray-500">{user?.email}</span>
          <button
            onClick={handleLogout}
            className="text-sm text-gray-700 border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  )
}
