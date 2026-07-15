import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import AppShell from './components/AppShell'
import BrowsePage from './pages/BrowsePage'
import GeneratePage from './pages/GeneratePage'
import SubscribePage from './pages/SubscribePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ReferencePage from './pages/admin/ReferencePage'
import ImportPage from './pages/admin/ImportPage'
import PapersPage from './pages/admin/PapersPage'
import PaperEditorPage from './pages/admin/PaperEditorPage'
import UserManagementPage from './pages/admin/UserManagementPage'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<AppShell />}>
            <Route path="/" element={<BrowsePage />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/generate" element={<GeneratePage />} />
              <Route path="/subscribe" element={<SubscribePage />} />
            </Route>
            <Route element={<ProtectedRoute requiredRole="admin" />}>
              <Route path="/admin/reference" element={<ReferencePage />} />
              <Route path="/admin/import" element={<ImportPage />} />
              <Route path="/admin/papers" element={<PapersPage />} />
              <Route path="/admin/papers/:id" element={<PaperEditorPage />} />
              <Route path="/admin/users" element={<UserManagementPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
