import { NavLink } from 'react-router-dom'
import { useHasRole } from '../hooks/useRoles'

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
  // 'platform-admin' is the Porth role for Estyn operators (platform administrators).
  // Tenant-level roles (ar_clerk, etc.) are configured per-tenant in claim role mappings.
  const isPlatformAdmin = useHasRole('platform-admin')
  const canSeeAR = useHasRole('ar_clerk', 'controller', 'platform-admin')
  const canSeeAP = useHasRole('ap_clerk', 'controller', 'platform-admin')
  const canSeeApprovals = useHasRole('controller', 'platform-admin')

  return (
    <nav className="w-56 bg-white border-r border-gray-200 flex flex-col py-4 shrink-0">
      <div className="px-4 mb-6">
        <span className="text-lg font-bold text-indigo-600">Porth</span>
        <span className="ml-1 text-xs text-gray-400">Admin</span>
      </div>
      <div className="flex-1 px-2 space-y-1">

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

        {isPlatformAdmin && (
          <>
            {sectionLabel('Platform Admin')}
            <NavLink to="/admin/platform/organizations" className={linkClass}>
              <span>🏢</span>Organizations
            </NavLink>

            {sectionLabel('Tenant Admin')}
            <NavLink to="/admin/tenant/users" className={linkClass}>
              <span>👤</span>Users
            </NavLink>
            <NavLink to="/admin/tenant/roles" className={linkClass}>
              <span>🔑</span>Roles
            </NavLink>
            <NavLink to="/admin/tenant/permissions" className={linkClass}>
              <span>🛡️</span>Permissions
            </NavLink>
            <NavLink to="/admin/tenant/claim-config" className={linkClass}>
              <span>⚙️</span>Claim Config
            </NavLink>
            <NavLink to="/admin/tenant/claim-mappings" className={linkClass}>
              <span>🔀</span>Claim Mappings
            </NavLink>
          </>
        )}
      </div>
    </nav>
  )
}
