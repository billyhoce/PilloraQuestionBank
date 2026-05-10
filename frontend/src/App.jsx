import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import AppShell from './components/AppShell'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ReferencePage from './pages/admin/ReferencePage'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<ProtectedRoute requiredRole="admin" />}>
            <Route element={<AppShell />}>
              <Route path="/admin/reference" element={<ReferencePage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/admin/reference" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
