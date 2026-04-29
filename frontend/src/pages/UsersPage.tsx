// PORTH-129 — User Management screen
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { usersApi } from '../api/users'
import { rolesApi } from '../api/roles'
import { tenantsApi } from '../api/tenants'
import { PLATFORM_ADMIN } from '../constants'
import type { User, Role, Tenant } from '../api/types'

export default function UsersPage() {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const orgId = currentUser?.porthUser.organization_id ?? ''
  // Platform admins pick from a tenant selector; tenant admins use their own tenant.
  const contextTenantId = currentUser?.porthUser.tenant_id ?? ''

  const [searchParams, setSearchParams] = useSearchParams()
  const tenantId = isPlatformAdmin
    ? (searchParams.get('tenantId') ?? '')
    : contextTenantId

  // Tenant selector (platform admin only)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [tenantsLoading, setTenantsLoading] = useState(false)

  // User list
  const [users, setUsers] = useState<User[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)

  // Email filter
  const [emailFilter, setEmailFilter] = useState('')

  // Side panel
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [panelRoles, setPanelRoles] = useState<Role[]>([]) // user's current roles
  const [allRoles, setAllRoles] = useState<Role[]>([])     // all roles in tenant
  const [rolesLoading, setRolesLoading] = useState(false)
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [suspending, setSuspending] = useState(false)

  // Load tenants for org
  useEffect(() => {
    if (!orgId) return
    setTenantsLoading(true)
    tenantsApi.listByOrg(orgId).then(setTenants).finally(() => setTenantsLoading(false))
  }, [orgId])

  // Load users when tenantId changes
  useEffect(() => {
    if (!orgId || !tenantId) return
    setUsersLoading(true)
    setUsersError(null)
    usersApi.listByTenant(orgId, tenantId)
      .then(setUsers)
      .catch(err => setUsersError(err instanceof Error ? err.message : String(err)))
      .finally(() => setUsersLoading(false))
  }, [orgId, tenantId])

  // Open side panel — load user roles and all tenant roles
  function openPanel(user: User) {
    setSelectedUser(user)
    setRolesLoading(true)
    setPanelRoles([])
    setAllRoles([])
    setSelectedRoleIds([])
    Promise.all([
      usersApi.getUserRoles(user.id, tenantId),
      rolesApi.list(tenantId),
    ])
      .then(([userRoles, tenantRoles]) => {
        setPanelRoles(userRoles)
        setAllRoles(tenantRoles)
        setSelectedRoleIds(userRoles.map(r => r.id))
      })
      .finally(() => setRolesLoading(false))
  }

  function closePanel() {
    setSelectedUser(null)
  }

  async function handleSuspendToggle() {
    if (!selectedUser) return
    const action = selectedUser.status === 'active' ? 'suspend' : 'reactivate'
    const verb = action === 'suspend' ? 'Suspend' : 'Reactivate'
    if (!window.confirm(`${verb} ${selectedUser.display_name ?? selectedUser.email}?`)) return
    setSuspending(true)
    try {
      const updated = action === 'suspend'
        ? await usersApi.suspend(selectedUser.id)
        : await usersApi.reactivate(selectedUser.id)
      setUsers(prev => prev.map(u => u.id === updated.id ? updated : u))
      setSelectedUser(updated)
    } finally {
      setSuspending(false)
    }
  }

  async function handleSaveRoles() {
    if (!selectedUser) return
    setSaving(true)
    try {
      await usersApi.setRoles(selectedUser.id, { tenant_id: tenantId, role_ids: selectedRoleIds })
      // Refresh displayed chips
      const updated = allRoles.filter(r => selectedRoleIds.includes(r.id))
      setPanelRoles(updated)
    } finally {
      setSaving(false)
    }
  }

  function handleTenantChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setSearchParams({ tenantId: e.target.value })
    setSelectedUser(null)
    setEmailFilter('')
  }

  function handleRoleSelectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const ids = Array.from(e.target.selectedOptions).map(o => o.value)
    setSelectedRoleIds(ids)
  }

  const filteredUsers = users.filter(u => {
    const q = emailFilter.toLowerCase()
    return !q || u.email.toLowerCase().includes(q) || (u.display_name ?? '').toLowerCase().includes(q)
  })

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Users</h1>
      </div>

      {/* Tenant selector — platform admin only */}
      {isPlatformAdmin && (
        <div className="mb-5">
          <label className="block text-xs font-medium text-gray-500 mb-1">Tenant</label>
          {tenantsLoading ? (
            <div className="animate-pulse bg-gray-200 rounded h-9 w-64" />
          ) : (
            <select
              value={tenantId}
              onChange={handleTenantChange}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 min-w-[260px]"
            >
              <option value="">— Select a tenant —</option>
              {tenants.map(t => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.display_name} ({t.environment_type})
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* Email filter */}
      {tenantId && (
        <div className="mb-4">
          <input
            type="text"
            placeholder="Search by email or name…"
            value={emailFilter}
            onChange={e => setEmailFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      )}

      {/* Error */}
      {usersError && (
        <div className="mb-4 px-4 py-3 bg-red-50 border border-red-300 text-red-700 rounded-lg text-sm">
          {usersError}
        </div>
      )}

      {/* User table */}
      {tenantId && (
        <div className={`bg-white border border-gray-200 rounded-lg overflow-hidden ${selectedUser ? 'mr-[380px]' : ''}`}>
          {usersLoading ? (
            <div className="p-6 space-y-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="animate-pulse bg-gray-200 rounded h-6 w-full" />
              ))}
            </div>
          ) : (
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Display Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Email</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-400">No users found.</td>
                  </tr>
                ) : filteredUsers.map(user => (
                  <tr
                    key={user.id}
                    onClick={() => openPanel(user)}
                    className={`cursor-pointer hover:bg-indigo-50 transition-colors ${selectedUser?.id === user.id ? 'bg-indigo-50' : ''}`}
                  >
                    <td className="px-4 py-3 text-gray-900 font-medium">
                      {user.display_name ?? (`${user.first_name ?? ''} ${user.last_name ?? ''}`.trim() || '—')}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{user.email}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={user.status} />
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {new Date(user.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {!tenantId && !tenantsLoading && (
        <p className="text-gray-400 text-sm mt-4">Select a tenant to view users.</p>
      )}

      {/* Side panel */}
      {selectedUser && (
        <div className="absolute top-0 right-0 w-[360px] bg-white border border-gray-200 rounded-lg shadow-xl flex flex-col">
          {/* Header */}
          <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200">
            <div>
              <p className="font-semibold text-gray-900">
                {selectedUser.display_name ?? (`${selectedUser.first_name ?? ''} ${selectedUser.last_name ?? ''}`.trim() || selectedUser.email)}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{selectedUser.email}</p>
              <div className="mt-1.5">
                <StatusBadge status={selectedUser.status} />
              </div>
            </div>
            <button
              onClick={closePanel}
              className="text-gray-400 hover:text-gray-600 text-lg leading-none ml-3"
              aria-label="Close panel"
            >
              ×
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
            {/* Suspend / Reactivate */}
            <div>
              <button
                onClick={handleSuspendToggle}
                disabled={suspending}
                className={`px-4 py-2 text-sm rounded-lg font-medium transition-colors disabled:opacity-60 ${
                  selectedUser.status === 'active'
                    ? 'bg-yellow-50 text-yellow-700 border border-yellow-300 hover:bg-yellow-100'
                    : 'bg-green-50 text-green-700 border border-green-300 hover:bg-green-100'
                }`}
              >
                {suspending ? 'Updating…' : selectedUser.status === 'active' ? 'Suspend User' : 'Reactivate User'}
              </button>
            </div>

            {/* Current roles chips */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">Current Roles</p>
              {rolesLoading ? (
                <div className="animate-pulse bg-gray-200 rounded h-6 w-full" />
              ) : panelRoles.length === 0 ? (
                <p className="text-xs text-gray-400">No roles assigned.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {panelRoles.map(r => (
                    <span key={r.id} className="bg-gray-100 text-gray-700 text-xs px-2 py-0.5 rounded-full">
                      {r.name}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Role multi-select */}
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">Add / Edit Roles</p>
              {rolesLoading ? (
                <div className="animate-pulse bg-gray-200 rounded h-24 w-full" />
              ) : (
                <>
                  <select
                    multiple
                    size={Math.min(allRoles.length + 1, 6)}
                    value={selectedRoleIds}
                    onChange={handleRoleSelectChange}
                    className="w-full border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {allRoles.map(r => (
                      <option key={r.id} value={r.id}>{r.name}</option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-400 mt-1">Hold ⌘/Ctrl to select multiple.</p>
                  <button
                    onClick={handleSaveRoles}
                    disabled={saving}
                    className="mt-3 w-full px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-60 font-medium"
                  >
                    {saving ? 'Saving…' : 'Save Roles'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: 'active' | 'suspended' }) {
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${
      status === 'active' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
    }`}>
      {status}
    </span>
  )
}
