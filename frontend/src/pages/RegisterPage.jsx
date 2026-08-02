import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'
import ErrorBanner from '../components/ErrorBanner'
import GoogleSignInButton from '../components/GoogleSignInButton'
import Spinner from '../components/Spinner'

export default function RegisterPage() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
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
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await api.auth.register({
        first_name: firstName,
        last_name: lastName,
        email,
        password,
      })
      navigate('/login')
    } catch (err) {
      setError(err.message || 'Registration failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      {/* Wider than the sign-in card to fit the side-by-side name fields. */}
      <div className="bg-white rounded-lg shadow p-8 w-full max-w-md">
        <h1 className="text-2xl font-semibold text-gray-900 mb-6">Create account</h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <ErrorBanner message={error} />
          <div className="flex gap-3">
            <div className="flex-1">
              <label htmlFor="register-first-name" className="block text-sm font-medium text-gray-700 mb-1">First name</label>
              <input
                id="register-first-name"
                type="text"
                required
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex-1">
              <label htmlFor="register-last-name" className="block text-sm font-medium text-gray-700 mb-1">Last name</label>
              <input
                id="register-last-name"
                type="text"
                required
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
          <div>
            <label htmlFor="register-email" className="block text-sm font-medium text-gray-700 mb-1">Email</label>
            <input
              id="register-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label htmlFor="register-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              id="register-password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              Min 8 characters, must include uppercase, lowercase, number, and special character.
            </p>
          </div>
          <div>
            <label htmlFor="register-confirm" className="block text-sm font-medium text-gray-700 mb-1">Confirm password</label>
            <input
              id="register-confirm"
              type="password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 rounded text-sm flex items-center justify-center gap-2"
          >
            {submitting && <Spinner size="sm" />}
            Create account
          </button>
        </form>
        {googleEnabled && (
          <>
            <div className="flex items-center gap-3 my-4">
              <span className="h-px flex-1 bg-gray-200" />
              <span className="text-xs text-gray-400">or</span>
              <span className="h-px flex-1 bg-gray-200" />
            </div>
            <GoogleSignInButton label="Sign up with Google" />
          </>
        )}
        <p className="mt-4 text-sm text-gray-500 text-center">
          Already have an account?{' '}
          <Link to="/login" className="text-blue-600 hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
