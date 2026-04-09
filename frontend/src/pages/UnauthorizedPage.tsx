import { useEffect, useState } from 'react'
import { useAuth0 } from '@auth0/auth0-react'

const AUTO_LOGOUT_SECONDS = 5

export default function UnauthorizedPage() {
  const { isAuthenticated, logout } = useAuth0()
  const [secondsLeft, setSecondsLeft] = useState(AUTO_LOGOUT_SECONDS)

  // If the user is authenticated, auto-logout after a short delay so they
  // are returned to the IdP login page.  A stale Auth0 session with no
  // Porth roles assigned should not leave the user stuck on this page.
  useEffect(() => {
    if (!isAuthenticated) return

    if (secondsLeft <= 0) {
      logout({ logoutParams: { returnTo: window.location.origin } })
      return
    }

    const timer = setTimeout(() => setSecondsLeft(s => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [isAuthenticated, secondsLeft, logout])

  const handleSignOut = () => {
    logout({ logoutParams: { returnTo: window.location.origin } })
  }

  return (
    <div className="flex h-screen items-center justify-center bg-gray-50">
      <div className="text-center max-w-sm">
        <p className="text-4xl font-bold text-gray-300 mb-4">403</p>
        <h1 className="text-lg font-semibold text-gray-900 mb-2">Access denied</h1>
        <p className="text-sm text-gray-500 mb-6">
          Your account doesn't have permission to access this application.
          Contact your administrator or sign in with a different account.
        </p>
        {isAuthenticated && (
          <>
            <button
              onClick={handleSignOut}
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Sign out
            </button>
            <p className="text-xs text-gray-400 mt-3">
              Signing out automatically in {secondsLeft}s…
            </p>
          </>
        )}
      </div>
    </div>
  )
}
