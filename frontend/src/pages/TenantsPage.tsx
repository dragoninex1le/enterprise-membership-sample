// PORTH-128 — Tenants admin screen
import { useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { organizationsApi } from '../api/organizations'
import { tenantsApi } from '../api/tenants'
import type { Organization, Tenant, CreateTenantRequest, UpdateTenantRequest } from '../api/types'

const ENV_TYPES = ['production', 'staging', 'development', 'sandbox'] as const
type EnvType = typeof ENV_TYPES[number]

interface TenantForm {
  tenant_id: string
  display_name: string
  environment_type: EnvType
}

const EMPTY_FORM: TenantForm = { tenant_id: '', display_name: '', environment_type: 'production' }

export default function TenantsPage() {
  const { orgId } = useParams<{ orgId: string }>()

  const [org, setOrg] = useState<Organization | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [modalOpen, setModalOpen] = useState(false)
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null)
  const [form, setForm] = useState<TenantForm>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    if (!orgId) return
    Promise.all([
      organizationsApi.get(orgId),
      tenantsApi.listByOrg(orgId),
    ])
      .then(([orgData, tenantData]) => {
        setOrg(orgData)
        setTenants(tenantData)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [orgId])

  function openNewModal() {
    setEditingTenant(null)
    setForm(EMPTY_FORM)
    setSubmitError(null)
    setModalOpen(true)
  }

  function openEditModal(tenant: Tenant) {
    setEditingTenant(tenant)
    setForm({ tenant_id: tenant.tenant_id, display_name: tenant.display_name, environment_type: tenant.environment_type })
    setSubmitError(null)
    setModalOpen(true)
  }

  function closeModal() {
    setModalOpen(false)
    setEditingTenant(null)
    setSubmitError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!orgId) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      if (editingTenant) {
        const body: UpdateTenantRequest = { display_name: form.display_name }
        const updated = await tenantsApi.update(editingTenant.tenant_id, body)
        setTenants(prev => prev.map(t => t.tenant_id === updated.tenant_id ? updated : t))
      } else {
        const body: CreateTenantRequest = { org_id: orgId, tenant_id: form.tenant_id, display_name: form.display_name, environment_type: form.environment_type }
        const created = await tenantsApi.create(body)
        setTenants(prev => [...prev, created])
      }
      closeModal()
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSuspend(tenant: Tenant) {
    if (!window.confirm(`Suspend "${tenant.display_name}"? This will prevent users in this tenant from authenticating.`)) return
    try {
      const updated = await tenantsApi.suspend(tenant.tenant_id)
      setTenants(prev => prev.map(t => t.tenant_id === updated.tenant_id ? updated : t))
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to suspend tenant')
    }
  }

  async function handleReactivate(tenant: Tenant) {
    if (!window.confirm(`Reactivate "${tenant.display_name}"?`)) return
    try {
      const updated = await tenantsApi.reactivate(tenant.tenant_id)
      setTenants(prev => prev.map(t => t.tenant_id === updated.tenant_id ? updated : t))
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to reactivate tenant')
    }
  }

  return (
    <div>
      {/* Org header */}
      <div className="mb-6">
        {loading ? (
          <div className="animate-pulse bg-gray-200 rounded h-8 w-64" />
        ) : org ? (
          <div className="flex items-center gap-3">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{org.name}</h1>
              <p className="text-xs text-gray-400 mt-0.5">slug: {org.slug}</p>
            </div>
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
              org.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            }`}>
              {org.status}
            </span>
          </div>
        ) : null}
      </div>

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-700">Tenants</h2>
        <button
          onClick={openNewModal}
          className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700"
        >
          + New Tenant
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="animate-pulse bg-gray-200 rounded h-12 w-full" />
          ))}
        </div>
      ) : tenants.length === 0 ? (
        <p className="text-gray-500 text-sm">No tenants for this organization.</p>
      ) : (
        <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
          <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3">Tenant ID</th>
              <th className="px-4 py-3">Display Name</th>
              <th className="px-4 py-3">Environment</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {tenants.map(tenant => (
              <tr key={tenant.tenant_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-xs text-gray-500">{tenant.tenant_id}</td>
                <td className="px-4 py-3 font-medium text-gray-900">{tenant.display_name}</td>
                <td className="px-4 py-3 text-gray-500">{tenant.environment_type}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                    tenant.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {tenant.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">
                  {new Date(tenant.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openEditModal(tenant)}
                      className="text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-100 text-gray-600"
                    >
                      Edit
                    </button>
                    {tenant.status === 'active' ? (
                      <button
                        onClick={() => handleSuspend(tenant)}
                        className="text-xs px-2 py-1 border border-red-200 rounded hover:bg-red-50 text-red-600"
                      >
                        Suspend
                      </button>
                    ) : tenant.status === 'suspended' ? (
                      <button
                        onClick={() => handleReactivate(tenant)}
                        className="text-xs px-2 py-1 border border-green-200 rounded hover:bg-green-50 text-green-600"
                      >
                        Reactivate
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Create / Edit Tenant Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              {editingTenant ? 'Edit Tenant' : 'New Tenant'}
            </h2>
            {submitError && (
              <div className="mb-3 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {submitError}
              </div>
            )}
            <form onSubmit={handleSubmit} className="space-y-4">
              {!editingTenant && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Tenant ID</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. acme-dev"
                    value={form.tenant_id}
                    onChange={e => setForm(f => ({ ...f, tenant_id: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <p className="mt-1 text-xs text-gray-400">Human-readable identifier — cannot be changed after creation.</p>
                </div>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                <input
                  type="text"
                  required
                  value={form.display_name}
                  onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              {!editingTenant && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Environment Type</label>
                  <select
                    value={form.environment_type}
                    onChange={e => setForm(f => ({ ...f, environment_type: e.target.value as EnvType }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {ENV_TYPES.map(t => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
              )}
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
                  {submitting ? (editingTenant ? 'Saving…' : 'Creating…') : (editingTenant ? 'Save' : 'Create')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
