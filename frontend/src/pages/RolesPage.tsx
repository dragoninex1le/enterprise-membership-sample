// PORTH-130 — Roles admin screen
import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'
import { rolesApi } from '../api/roles'
import { permissionsApi } from '../api/permissions'
import type { Role, Permission, CreateRoleRequest } from '../api/types'

interface NewRoleForm { name: string; description: string }
const EMPTY_FORM: NewRoleForm = { name: '', description: '' }

function groupByCategory(permissions: Permission[]): Record<string, Permission[]> {
  return permissions.reduce<Record<string, Permission[]>>((acc, p) => {
    const cat = p.category ?? 'Uncategorised'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(p)
    return acc
  }, {})
}

export default function RolesPage() {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const [searchParams] = useSearchParams()
  const tenantId = isPlatformAdmin
    ? (searchParams.get('tenantId') ?? '')
    : (currentUser?.porthUser.tenant_id ?? '')

  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState<NewRoleForm>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const [selectedRole, setSelectedRole] = useState<Role | null>(null)
  const [allPermissions, setAllPermissions] = useState<Permission[]>([])
  const [assignedKeys, setAssignedKeys] = useState<string[]>([])
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set())
  const [panelLoading, setPanelLoading] = useState(false)
  const [panelError, setPanelError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const fetchRoles = useCallback(() => {
    setLoading(true)
    rolesApi.list(tenantId)
      .then(setRoles)
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load roles'))
      .finally(() => setLoading(false))
  }, [tenantId])

  useEffect(() => {
    if (tenantId) fetchRoles()
  }, [fetchRoles, tenantId])

  async function openPanel(role: Role) {
    setSelectedRole(role)
    setPanelLoading(true)
    setPanelError(null)
    setSaveError(null)
    setAllPermissions([])
    setAssignedKeys([])
    setSelectedKeys(new Set())
    try {
      const [allPerms, assignedPermsKeys] = await Promise.all([
        permissionsApi.list(tenantId),
        rolesApi.getPermissions(tenantId, role.id),
      ])
      setAllPermissions(allPerms)
      setAssignedKeys(assignedPermsKeys)
      setSelectedKeys(new Set(assignedPermsKeys))
    } catch (e) {
      setPanelError(e instanceof Error ? e.message : 'Failed to load permissions')
    } finally {
      setPanelLoading(false)
    }
  }

  function closePanel() {
    setSelectedRole(null)
    setAllPermissions([])
    setAssignedKeys([])
    setSelectedKeys(new Set())
    setPanelError(null)
    setSaveError(null)
  }

  function toggleKey(key: string) {
    setSelectedKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function handleSavePermissions() {
    if (!selectedRole) return
    setSaving(true)
    setSaveError(null)
    try {
      await rolesApi.setPermissions(tenantId, selectedRole.id, [...selectedKeys])
      setAssignedKeys([...selectedKeys])
      fetchRoles()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Failed to save permissions')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteRole() {
    if (!selectedRole) return
    if (!window.confirm(`Delete role "${selectedRole.name}"? This cannot be undone.`)) return
    setDeleting(true)
    try {
      await rolesApi.delete(tenantId, selectedRole.id)
      setRoles(prev => prev.filter(r => r.id !== selectedRole.id))
      closePanel()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Failed to delete role')
    } finally {
      setDeleting(false)
    }
  }

  function openModal() {
    setForm(EMPTY_FORM)
    setSubmitError(null)
    setModalOpen(true)
  }

  function closeModal() {
    setModalOpen(false)
    setSubmitError(null)
  }

  async function handleCreateRole(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setSubmitError(null)
    const body: CreateRoleRequest = { tenant_id: tenantId, name: form.name, description: form.description }
    try {
      await rolesApi.create(body)
      fetchRoles()
      closeModal()
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Failed to create role')
    } finally {
      setSubmitting(false)
    }
  }

  const grouped = groupByCategory(allPermissions)
  const isDirty = JSON.stringify([...selectedKeys].sort()) !== JSON.stringify([...assignedKeys].sort())

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Roles</h1>
        <button
          onClick={openModal}
          className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700"
        >
          + New Role
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="animate-pulse bg-gray-200 rounded h-6 w-full" />
          ))}
        </div>
      ) : roles.length === 0 ? (
        <p className="text-gray-500 text-sm">No roles found for this tenant.</p>
      ) : (
        <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
          <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Permissions</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {roles.map(role => (
              <tr
                key={role.id}
                onClick={() => openPanel(role)}
                className={`cursor-pointer hover:bg-indigo-50 transition-colors ${selectedRole?.id === role.id ? 'bg-indigo-50' : ''}`}
              >
                <td className="px-4 py-3 font-medium text-gray-900">{role.name}</td>
                <td className="px-4 py-3 text-gray-500">{role.description ?? '—'}</td>
                <td className="px-4 py-3 text-gray-500">
                  <span className="text-indigo-600 text-xs">view</span>
                </td>
                <td className="px-4 py-3">
                  {role.is_system && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                      system
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400">
                  {new Date(role.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Side Panel */}
      {selectedRole && (
        <div className="fixed top-0 right-0 h-full w-96 bg-white shadow-2xl border-l border-gray-200 z-40 flex flex-col overflow-hidden">
          <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100">
            <div className="flex-1 min-w-0 pr-4">
              <h2 className="text-base font-semibold text-gray-900 truncate">{selectedRole.name}</h2>
              {selectedRole.description && (
                <p className="text-xs text-gray-500 mt-0.5">{selectedRole.description}</p>
              )}
              {selectedRole.is_system && (
                <span className="inline-flex items-center mt-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                  system
                </span>
              )}
            </div>
            <button
              onClick={closePanel}
              className="text-gray-400 hover:text-gray-600 text-xl font-light leading-none mt-0.5"
              aria-label="Close"
            >
              ×
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4">
            {panelLoading ? (
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="animate-pulse bg-gray-200 rounded h-6 w-full" />
                ))}
              </div>
            ) : panelError ? (
              <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
                {panelError}
              </div>
            ) : Object.keys(grouped).length === 0 ? (
              <p className="text-gray-500 text-sm">No permissions registered for this tenant.</p>
            ) : (
              <div className="space-y-5">
                {Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([cat, perms]) => (
                  <div key={cat}>
                    <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">{cat}</h3>
                    <div className="space-y-1">
                      {perms.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)).map(p => (
                        <label key={p.key} className="flex items-start gap-2 cursor-pointer group">
                          <input
                            type="checkbox"
                            checked={selectedKeys.has(p.key)}
                            onChange={() => toggleKey(p.key)}
                            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className="text-sm text-gray-700 group-hover:text-gray-900">
                            {p.display_name}
                            <span className="ml-1 text-xs text-gray-400 font-mono">{p.key}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="px-5 py-4 border-t border-gray-100 space-y-2">
            {saveError && (
              <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
                {saveError}
              </div>
            )}
            <div className="flex items-center gap-3">
              <button
                onClick={handleSavePermissions}
                disabled={saving || panelLoading || !isDirty}
                className="flex-1 px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? 'Saving…' : 'Save Permissions'}
              </button>
              {!selectedRole.is_system && (
                <button
                  onClick={handleDeleteRole}
                  disabled={deleting}
                  className="px-4 py-2 text-sm bg-white text-red-600 border border-red-300 rounded-lg hover:bg-red-50 disabled:opacity-50"
                >
                  {deleting ? 'Deleting…' : 'Delete Role'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* New Role Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">New Role</h2>
            {submitError && (
              <div className="mb-3 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {submitError}
              </div>
            )}
            <form onSubmit={handleCreateRole} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                  type="text"
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                >
                  {submitting ? 'Creating…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
