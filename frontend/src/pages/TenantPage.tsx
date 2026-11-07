// One tenant, as a platform admin manages it: its roles and its claim mapping, named by the tenant.
// Reached from Tenants ("Manage →"). Roles and claim mapping are per tenant, so they live here and
// nowhere a platform admin could open them without having chosen a tenant.
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useParams } from 'react-router-dom'
import { tenantsApi } from '../api/tenants'
import type { Tenant } from '../api/types'
import { tenantPagePath } from '../hooks/useManagedTenant'

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 text-sm border-b-2 -mb-px ${
    isActive ? 'border-indigo-600 text-indigo-700 font-medium' : 'border-transparent text-gray-500 hover:text-gray-700'
  }`

export default function TenantPage() {
  const { tenantId = '' } = useParams()
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setTenant(null)
    setError(null)
    let live = true
    tenantsApi
      .find(tenantId)
      .then((found) => {
        if (!live) return
        if (found) setTenant(found)
        else setError(`There is no tenant ${tenantId}.`)
      })
      .catch((err) => {
        if (!live) return
        const status = err?.response?.status
        setError(`Failed to load the tenant${status ? ` (HTTP ${status})` : ''}.`)
      })
    return () => { live = false }
  }, [tenantId])

  return (
    <div>
      <Link to="/admin/platform/tenants" className="text-sm text-indigo-600 hover:underline">
        ← All tenants
      </Link>
      <div className="mt-2 mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{tenant?.display_name ?? tenantId}</h1>
        <p className="text-sm text-gray-500">
          <span className="font-mono">{tenantId}</span>
          {tenant?.org_name && <> · {tenant.org_name}</>}
          {tenant?.tenant_tier && <> · {tenant.tenant_tier}</>}
          {tenant?.status && <> · {tenant.status}</>}
        </p>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      <nav className="flex gap-2 border-b border-gray-200 mb-6">
        <NavLink to={tenantPagePath(tenantId, 'roles')} className={tabClass}>Roles</NavLink>
        <NavLink to={tenantPagePath(tenantId, 'claim-mapping')} className={tabClass}>Claim mapping</NavLink>
      </nav>

      <Outlet />
    </div>
  )
}
