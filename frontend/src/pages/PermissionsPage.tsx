// PORTH-130 — Permissions read-only listing screen
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'
import { permissionsApi } from '../api/permissions'
import type { Permission } from '../api/types'

function groupByCategory(permissions: Permission[]): Record<string, Permission[]> {
  return permissions.reduce<Record<string, Permission[]>>((acc, p) => {
    const cat = p.category ?? 'Uncategorised'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(p)
    return acc
  }, {})
}

export default function PermissionsPage() {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const [searchParams] = useSearchParams()
  const tenantId = isPlatformAdmin
    ? (searchParams.get('tenantId') ?? '')
    : (currentUser?.porthUser.tenant_id ?? '')

  const [permissions, setPermissions] = useState<Permission[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!tenantId) return
    permissionsApi.list(tenantId)
      .then(setPermissions)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load permissions'))
      .finally(() => setLoading(false))
  }, [tenantId])

  const grouped = groupByCategory(permissions)

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Permissions</h1>
        <p className="mt-1 text-sm text-gray-500">
          Permissions are registered via the bootstrap script, not created through the UI.
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="animate-pulse bg-gray-200 rounded h-6 w-full" />
          ))}
        </div>
      ) : permissions.length === 0 ? (
        <p className="text-gray-500 text-sm">No permissions registered for this tenant.</p>
      ) : (
        <div className="space-y-8">
          {Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([category, perms]) => (
            <div key={category}>
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">{category}</h2>
              <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
                <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="px-4 py-3">Key</th>
                    <th className="px-4 py-3">Display Name</th>
                    <th className="px-4 py-3">Sort Order</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {perms.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)).map(p => (
                    <tr key={p.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono text-xs text-indigo-700">{p.key}</td>
                      <td className="px-4 py-3 text-gray-800">{p.display_name}</td>
                      <td className="px-4 py-3 text-gray-400">{p.sort_order ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
