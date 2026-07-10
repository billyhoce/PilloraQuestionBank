import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Top-right account button: shows the user's email and toggles a dropdown
// holding "Log out". Closes on outside click or Escape.
export default function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function onMouseDown(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    function onKeyDown(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  async function handleLogout() {
    setOpen(false)
    await logout()
    navigate('/')
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-sm text-gray-700 border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
      >
        {user?.email}
        <span aria-hidden="true" className="text-gray-400 text-xs">▾</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 mt-1 w-36 bg-white border border-gray-200 rounded shadow-lg py-1 z-20"
        >
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="w-full text-left px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            Log out
          </button>
        </div>
      ) : null}
    </div>
  )
}
