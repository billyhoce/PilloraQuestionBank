import { Outlet } from 'react-router-dom'
import NavBar from './NavBar'

// Shared layout for all main pages: the role-aware menubar plus page content.
export default function AppShell() {
  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  )
}
