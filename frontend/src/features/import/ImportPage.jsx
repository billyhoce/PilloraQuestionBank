import { Navigate } from 'react-router-dom'
import { MANUAL_SESSION_KEY } from './manualHandoff'

function manualInProgress() {
  try {
    return sessionStorage.getItem(MANUAL_SESSION_KEY) !== null
  } catch {
    return false
  }
}

// `/admin/import` itself: Auto import, unless a Manual import is mid-way (its step lives in
// sessionStorage), so a reload or a "Handle manually" hand-off lands back on it.
export default function ImportPage() {
  return <Navigate to={manualInProgress() ? '/admin/import/manual' : '/admin/import/auto'} replace />
}
