import { NavLink, useParams } from 'react-router-dom'

const topNav = [
  { label: 'Organizations', to: '/organizations', icon: '🏢' },
]

const tenantNav = (orgId: string, tenantId: string) => [
  { label: 'Users',          to: `/organizations/${orgId}/tenants/${tenantId}/users`,          icon: '👤' },
  { label: 'Roles',          to: `/organizations/${orgId}/tenants/${tenantId}/roles`,          icon: '🔑' },
  { label: 'Permissions',    to: `/organizations/${orgId}/tenants/${tenantId}/permissions`,    icon: '🛡️' },
  { label: 'Claim Config',   to: `/organizations/${orgId}/tenants/${tenantId}/claim-config`,   icon: '⚙️' },
  { label: 'Claim Mappings', to: `/organizations/${orgId}/tenants/${tenantId}/claim-mappings`, icon: '🔀' },
]

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${
    isActive ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-600 hover:bg-gray-100'
  }`

export default function Sidebar() {
  const { orgId, tenantId } = useParams()

  return (
    <nav className="w-56 bg-white border-r border-gray-200 flex flex-col py-4 shrink-0">
      <div className="px-4 mb-6">
        <span className="text-lg font-bold text-indigo-600">Porth</span>
        <span className="ml-1 text-xs text-gray-400">Admin</span>
      </div>
      <div className="flex-1 px-2 space-y-1">
        {topNav.map(item => (
          <NavLink key={item.to} to={item.to} className={linkClass}>
            <span>{item.icon}</span>{item.label}
          </NavLink>
        ))}
        {orgId && tenantId && (
          <>
            <div className="pt-4 pb-1 px-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Tenant</div>
            {tenantNav(orgId, tenantId).map(item => (
              <NavLink key={item.to} to={item.to} className={linkClass}>
                <span>{item.icon}</span>{item.label}
              </NavLink>
            ))}
          </>
        )}
      </div>
    </nav>
  )
}
