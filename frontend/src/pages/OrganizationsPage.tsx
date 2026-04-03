// PORTH-128 — Build Organization and Tenant management screens
import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { organizationsApi } from '../api/organizations'
import type { Organization } from '../api/types'

export default function OrganizationsPage() {
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    organizationsApi.list()
      .then(setOrgs)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-gray-500 text-sm">Loading organizations…</div>
  if (error)   return <div className="text-red-600 text-sm">Error: {error}</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Organizations</h1>
        <button className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700">
          + New Organization
        </button>
      </div>
      {orgs.length === 0 ? (
        <p className="text-gray-500 text-sm">No organizations yet.</p>
      ) : (
        <div className="grid gap-3">
          {orgs.map(org => (
            <Link
              key={org.id}
              to={`/admin/platform/organizations/${org.id}/tenants`}
              className="bg-white border border-gray-200 rounded-lg px-5 py-4 flex items-center justify-between hover:border-indigo-300 transition-colors"
            >
              <div>
                <p className="font-medium text-gray-900">{org.name}</p>
                <p className="text-xs text-gray-400 mt-0.5">slug: {org.slug}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                org.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
              }`}>{org.status}</span>
            </Link>
          ))}
        </div>
      )}
      <p className="mt-6 text-xs text-gray-400">Full create/edit forms — PORTH-128</p>
    </div>
  )
}
