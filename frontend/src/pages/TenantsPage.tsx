// PORTH-128 — Build Organization and Tenant management screens
import { useParams, Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { tenantsApi } from '../api/tenants'
import type { Tenant } from '../api/types'

export default function TenantsPage() {
  const { orgId } = useParams<{ orgId: string }>()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (orgId) tenantsApi.listByOrg(orgId).then(setTenants).finally(() => setLoading(false))
  }, [orgId])

  if (loading) return <div className="text-gray-500 text-sm">Loading tenants…</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
        <button className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700">+ New Tenant</button>
      </div>
      <div className="grid gap-3">
        {tenants.map(t => (
          <Link key={t.tenant_id} to={`/admin/tenant/users`}
            className="bg-white border border-gray-200 rounded-lg px-5 py-4 flex items-center justify-between hover:border-indigo-300 transition-colors">
            <div>
              <p className="font-medium text-gray-900">{t.display_name}</p>
              <p className="text-xs text-gray-400 mt-0.5">{t.environment_type}</p>
            </div>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              t.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>{t.status}</span>
          </Link>
        ))}
      </div>
      <p className="mt-6 text-xs text-gray-400">Full create/edit forms — PORTH-128</p>
    </div>
  )
}
