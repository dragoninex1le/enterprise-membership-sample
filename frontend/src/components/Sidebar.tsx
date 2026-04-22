import { NavLink } from 'react-router-dom'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'

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

  // Tenant-level app roles — these do not include platform-admin because
  // platform admins have no business in the tenant application pages.
  const canSeeAR = useHasRole('ar_clerk', 'controller')
  const canSeeAP = useHasRole('ap_clerk', 'controller')
  const canSeeApprovals = useHasRole('controller')

  return (
    <nav className="w-56 bg-white border-r border-gray-200 flex flex-col py-4 shrink-0">
      <div className="px-4 mb-6">
        <span className="text-lg font-bold text-indigo-600">Porth</span>
        <span className="ml-1 text-xs text-gray-400">Admin</span>
      </div>
      <div className="flex-1 px-2 space-y-1">

        {isPlatformAdmin ? (
          // Platform admins only manage organisations and tenants — no app sections.
          <>
            {sectionLabel('Platform Admin')}
            <NavLink to="/admin/platform/organizations" className={linkClass}>
              <span>🏢</span>Organizations
            </NavLink>
          </>
        ) : (
          // Tenant users see app-level pages based on their assigned roles.
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
          </>
        )}
      </div>
    </nav>
  )
}
