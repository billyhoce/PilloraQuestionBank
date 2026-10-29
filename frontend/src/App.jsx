import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { SiteConfigProvider } from './context/SiteConfigContext'
import ProtectedRoute from './components/ProtectedRoute'
import AppShell from './components/AppShell'
import AboutPage from './pages/AboutPage'
import BrowsePage from './pages/BrowsePage'
import GeneratePage from './pages/GeneratePage'
import SubscribePage from './pages/SubscribePage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import ReferencePage from './pages/admin/ReferencePage'
import ImportPage from './pages/admin/ImportPage'
import ImportLayout from './pages/admin/ImportLayout'
import AutoImportPage from './pages/admin/AutoImportPage'
import ReviewQueuePage from './pages/admin/ReviewQueuePage'
import ManualImportPage from './pages/admin/ManualImportPage'
import ReviewPage from './pages/admin/ReviewPage'
import PapersPage from './pages/admin/PapersPage'
import PaperEditorPage from './pages/admin/PaperEditorPage'
import UserManagementPage from './pages/admin/UserManagementPage'
import GenerationConfigPage from './pages/admin/GenerationConfigPage'
import { UploadQueueProvider } from './features/import/UploadQueue'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SiteConfigProvider>
          {/* Above the routes so auto-import uploads keep going while an admin moves between pages. */}
          <UploadQueueProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route element={<AppShell />}>
                <Route path="/" element={<BrowsePage />} />
                {/* Public, like `/` — the About page is outward-facing copy. */}
                <Route path="/about" element={<AboutPage />} />
                <Route element={<ProtectedRoute />}>
                  <Route path="/generate" element={<GeneratePage />} />
                  <Route path="/subscribe" element={<SubscribePage />} />
                </Route>
                <Route element={<ProtectedRoute requiredRole="admin" />}>
                  <Route path="/admin/reference" element={<ReferencePage />} />
                  <Route path="/admin/import" element={<ImportPage />} />
                  <Route element={<ImportLayout />}>
                    <Route path="/admin/import/auto" element={<AutoImportPage />} />
                    <Route path="/admin/import/review" element={<ReviewQueuePage />} />
                    <Route path="/admin/import/manual" element={<ManualImportPage />} />
                    <Route path="/admin/import/jobs/:jobId/review" element={<ReviewPage />} />
                  </Route>
                  <Route path="/admin/papers" element={<PapersPage />} />
                  <Route path="/admin/papers/:id" element={<PaperEditorPage />} />
                  <Route path="/admin/users" element={<UserManagementPage />} />
                  <Route path="/admin/generation-config" element={<GenerationConfigPage />} />
                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </UploadQueueProvider>
        </SiteConfigProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
