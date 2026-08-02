import { useAuth } from '@estyn/porth-admin/auth'
import { usePorthContext } from '../context/PorthContext'

const ROLES_CLAIM = 'https://porth.io/roles'

export default function UnauthorizedPage() {
  const { isAuthenticated, signoutRedirect, user } = useAuth()
  const { currentUser, userError, tenantConfig } = usePorthContext()

  // Roles claim as resolved server-side and passed through on the session
  // profile. The browser never sees a JWT under the BFF (ADR-Z9), so this
  // reads from `user.claims`, not a decoded token.
  const jwtRolesClaim: string[] = (user?.claims?.[ROLES_CLAIM] as string[]) ?? []

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
              <span className="text-gray-500">Session sub: </span>
              <span className="text-gray-900">{user?.sub ?? '—'}</span>
            </div>

            <div>
              <span className="text-gray-500">Session email: </span>
              <span className="text-gray-900">{user?.email ?? '—'}</span>
            </div>

            <div>
              <span className="text-gray-500">JWT roles claim </span>
              <span className="text-gray-400">({ROLES_CLAIM}): </span>
              {jwtRolesClaim.length > 0
                ? <span className="text-green-700">[{jwtRolesClaim.join(', ')}]</span>
                : <span className="text-red-500">[ ] (missing or empty — check the claim mapping)</span>
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
              onClick={() => signoutRedirect(window.location.origin)}
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
