import { NavLink } from 'react-router-dom'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN, SAMPLE_ROLES } from '../constants'

const { TENANT_ADMIN, AR_CLERK, AP_CLERK, CONTROLLER } = SAMPLE_ROLES

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
    isActive ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-600 hover:bg-gray-100'
  }`

const sectionLabel = (label: string) => (
  <div className="pt-4 pb-1 px-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">
    {label}
  </div>
)

export default function Sidebar() {
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const isTenantAdmin = useHasRole(TENANT_ADMIN)
  const canSeeAR = useHasRole(AR_CLERK, CONTROLLER, TENANT_ADMIN)
  const canSeeAP = useHasRole(AP_CLERK, CONTROLLER, TENANT_ADMIN)
  const canSeeApprovals = useHasRole(CONTROLLER, TENANT_ADMIN)

  return (
    <nav className="w-56 bg-white border-r border-gray-200 flex flex-col py-4 shrink-0">
      <div className="px-4 mb-6">
        <span className="text-lg font-bold text-indigo-600">Porth</span>
        <span className="ml-1 text-xs text-gray-400">Admin</span>
      </div>
      <div className="flex-1 px-2 space-y-1">

        {isPlatformAdmin ? (
          <>
            {sectionLabel('Platform Admin')}
            <NavLink to="/admin/platform/organizations" className={linkClass}>
              <span>🏢</span>Organizations
            </NavLink>
          </>
        ) : (
          <>
            {sectionLabel('Main')}
            <NavLink to="/dashboard" className={linkClass}>
              <span>📊</span>Dashboard
            </NavLink>
            {canSeeAR && (
              <NavLink to="/ar" className={linkClass}>
                <span>📥</span>Accounts Receivable
              </NavLink>
            )}
            {canSeeAP && (
              <NavLink to="/ap" className={linkClass}>
                <span>📤</span>Accounts Payable
              </NavLink>
            )}
            {canSeeApprovals && (
              <NavLink to="/approvals" className={linkClass}>
                <span>✅</span>Approvals
              </NavLink>
            )}

            {isTenantAdmin && (
              <>
                {sectionLabel('Tenant Admin')}
                <NavLink to="/admin/tenant/users" className={linkClass}>
                  <span>👥</span>Users
                </NavLink>
                <NavLink to="/admin/tenant/roles" className={linkClass}>
                  <span>🔑</span>Roles
                </NavLink>
                <NavLink to="/admin/tenant/permissions" className={linkClass}>
                  <span>🛡</span>Permissions
                </NavLink>
                <NavLink to="/admin/tenant/claim-config" className={linkClass}>
                  <span>🗂</span>Claim Mapping
                </NavLink>
              </>
            )}
          </>
        )}
      </div>
    </nav>
  )
}
