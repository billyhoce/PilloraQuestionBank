import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'
import ErrorBanner from '../components/ErrorBanner'
import GoogleSignInButton from '../components/GoogleSignInButton'
import Spinner from '../components/Spinner'

// Codes the backend appends to /login?error=... when a Google sign-in fails.
// The user arrives here mid-redirect, so the message has to live on this page.
const OAUTH_ERRORS = {
  google_cancelled: 'Google sign-in was cancelled.',
  google_state_mismatch: 'That Google sign-in link expired. Please try again.',
  google_email_unverified: 'Your Google email address is not verified.',
  google_failed: 'Could not sign in with Google. Please try again.',
}

export default function LoginPage() {
  const { user, loading, login } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(
    () => OAUTH_ERRORS[searchParams.get('error')] || '',
  )
  const [submitting, setSubmitting] = useState(false)
  const [googleEnabled, setGoogleEnabled] = useState(false)

  useEffect(() => {
    api.auth.providers()
      .then((p) => setGoogleEnabled(Boolean(p?.google)))
      .catch(() => setGoogleEnabled(false))
  }, [])

  if (!loading && user) return <Navigate to="/" replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError(err.message || 'Login failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow p-8 w-full max-w-sm">
        <h1 className="text-2xl font-semibold text-gray-900 mb-6">Sign in</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <ErrorBanner message={error} />
          <div>
            <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              id="login-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              id="login-password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 rounded text-sm flex items-center justify-center gap-2"
          >
            {submitting && <Spinner size="sm" />}
            Sign in
          </button>
        </form>
        {googleEnabled && (
          <>
            <div className="flex items-center gap-3 my-4">
              <span className="h-px flex-1 bg-gray-200" />
              <span className="text-xs text-gray-400">or</span>
              <span className="h-px flex-1 bg-gray-200" />
            </div>
            <GoogleSignInButton label="Sign in with Google" />
          </>
        )}
        <p className="mt-4 text-sm text-gray-500 text-center">
          Don't have an account?{' '}
          <Link to="/register" className="text-blue-600 hover:underline">Register</Link>
        </p>
      </div>
    </div>
  )
}
