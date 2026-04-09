import { useEffect, useState } from 'react'
import { useAuth0 } from '@auth0/auth0-react'
import { usePorthContext } from '../context/PorthContext'

const AUTO_LOGOUT_SECONDS = 5
const ROLES_CLAIM = 'https://porth.io/roles'

export default function UnauthorizedPage() {
  const { isAuthenticated, logout, user: auth0User } = useAuth0()
  const { currentUser, userError, tenantConfig } = usePorthContext()
  const [secondsLeft, setSecondsLeft] = useState(AUTO_LOGOUT_SECONDS)

  useEffect(() => {
    if (!isAuthenticated) return
    if (secondsLeft <= 0) {
      logout({ logoutParams: { returnTo: window.location.origin } })
      return
    }
    const timer = setTimeout(() => setSecondsLeft(s => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [isAuthenticated, secondsLeft, logout])

  // Pull the roles claim out of the Auth0 JWT payload for display
  const jwtRolesClaim: string[] = (auth0User as Record<string, unknown>)?.[ROLES_CLAIM] as string[] ?? []

  return (
    <div className="flex h-screen items-center justify-center bg-gray-50 p-6">
      <div className="w-full max-w-lg">
        {/* ── Error header ───────────────────────────────────────────── */}
        <div className="text-center mb-6">
          <p className="text-4xl font-bold text-gray-300 mb-2">403</p>
          <h1 className="text-lg font-semibold text-gray-900 mb-1">Access denied</h1>
          <p className="text-sm text-gray-500">
            Your account doesn't have permission to access this application.
          </p>
        </div>

        {/* ── Debug panel ────────────────────────────────────────────── */}
        {isAuthenticated && (
          <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6 text-left text-xs font-mono space-y-3">
            <p className="text-gray-400 uppercase tracking-wide text-[10px] font-sans font-semibold">
              Auth debug
            </p>

            <div>
              <span className="text-gray-500">Auth0 sub: </span>
              <span className="text-gray-900">{auth0User?.sub ?? '—'}</span>
            </div>

            <div>
              <span className="text-gray-500">Auth0 email: </span>
              <span className="text-gray-900">{auth0User?.email ?? '—'}</span>
            </div>

            <div>
              <span className="text-gray-500">JWT roles claim </span>
              <span className="text-gray-400">({ROLES_CLAIM}): </span>
              {jwtRolesClaim.length > 0
                ? <span className="text-green-700">[{jwtRolesClaim.join(', ')}]</span>
                : <span className="text-red-500">[ ] (missing or empty — check Auth0 Action)</span>
              }
            </div>

            <div>
              <span className="text-gray-500">Tenant: </span>
              <span className="text-gray-900">{tenantConfig?.tenantId ?? '—'}</span>
              <span className="text-gray-400"> / org: </span>
              <span className="text-gray-900">{tenantConfig?.organizationId ?? '—'}</span>
            </div>

            <div>
              <span className="text-gray-500">Porth user id: </span>
              <span className="text-gray-900">{currentUser?.porthUser?.id ?? '—'}</span>
            </div>

            <div>
              <span className="text-gray-500">Porth roles (DynamoDB): </span>
              {currentUser && currentUser.roles.length > 0
                ? <span className="text-green-700">[{currentUser.roles.map(r => r.name).join(', ')}]</span>
                : <span className="text-red-500">[ ] (no roles assigned in Porth)</span>
              }
            </div>

            {userError && (
              <div>
                <span className="text-gray-500">User load error: </span>
                <span className="text-red-600">{userError}</span>
              </div>
            )}
          </div>
        )}

        {/* ── Actions ────────────────────────────────────────────────── */}
        {isAuthenticated && (
          <div className="text-center">
            <button
              onClick={() => logout({ logoutParams: { returnTo: window.location.origin } })}
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Sign out
            </button>
            <p className="text-xs text-gray-400 mt-3">
              Signing out automatically in {secondsLeft}s…
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
