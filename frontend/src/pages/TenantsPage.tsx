// PORTH-128 — Flat tenant list with org filter, New Org, New Tenant (incl. IdP), Edit Tenant (incl. IdP)
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { organizationsApi } from '../api/organizations'
import { tenantsApi } from '../api/tenants'
import type { Organization, Tenant, CreateOrganizationRequest, CreateTenantRequest, UpdateTenantRequest, IdpConfig } from '../api/types'

const ENV_TYPES = ['production', 'staging', 'development', 'sandbox'] as const
type EnvType = typeof ENV_TYPES[number]

interface TenantRow extends Tenant { org_name: string }

interface NewOrgForm { name: string; slug: string }
interface NewTenantForm {
  org_id: string; tenant_id: string; display_name: string; environment_type: EnvType
  idp_enabled: boolean; idp_domain: string; idp_client_id: string; idp_audience: string
}
interface EditTenantForm {
  display_name: string
  idp_enabled: boolean; idp_domain: string; idp_client_id: string; idp_audience: string
}

const EMPTY_ORG: NewOrgForm = { name: '', slug: '' }
const EMPTY_TENANT: NewTenantForm = { org_id: '', tenant_id: '', display_name: '', environment_type: 'production', idp_enabled: false, idp_domain: '', idp_client_id: '', idp_audience: '' }

function idpFromForm(f: { idp_enabled: boolean; idp_domain: string; idp_client_id: string; idp_audience: string }): IdpConfig | undefined {
  if (!f.idp_enabled) return undefined
  return { provider: 'auth0', domain: f.idp_domain, client_id: f.idp_client_id, audience: f.idp_audience || undefined }
}

function IdpFields<T extends { idp_enabled: boolean; idp_domain: string; idp_client_id: string; idp_audience: string }>(
  { prefix, form, setForm }: { prefix: string; form: T; setForm: (fn: (f: T) => T) => void }
) {
  return (
    <div className="border-t border-gray-100 pt-4">
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={form.idp_enabled}
          onChange={e => setForm(f => ({ ...f, idp_enabled: e.target.checked }))}
          className="rounded" />
        <span className="text-sm font-medium text-gray-700">Identity Provider (Auth0)</span>
      </label>
      {form.idp_enabled && (
        <div className="mt-3 space-y-3">
          <div>
            <label htmlFor={`${prefix}-domain`} className="block text-sm font-medium text-gray-700 mb-1">Domain</label>
            <input id={`${prefix}-domain`} type="text" required value={form.idp_domain}
              onChange={e => setForm(f => ({ ...f, idp_domain: e.target.value }))}
              placeholder="your-tenant.auth0.com"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
          <div>
            <label htmlFor={`${prefix}-cid`} className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
            <input id={`${prefix}-cid`} type="text" required value={form.idp_client_id}
              onChange={e => setForm(f => ({ ...f, idp_client_id: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
          <div>
            <label htmlFor={`${prefix}-aud`} className="block text-sm font-medium text-gray-700 mb-1">Audience <span className="text-gray-400 font-normal">(optional)</span></label>
            <input id={`${prefix}-aud`} type="text" value={form.idp_audience}
              onChange={e => setForm(f => ({ ...f, idp_audience: e.target.value }))}
              placeholder="https://your-api.example.com"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          </div>
        </div>
      )}
    </div>
  )
}

export default function TenantsPage() {
  const navigate = useNavigate()
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [tenants, setTenants] = useState<TenantRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterOrgId, setFilterOrgId] = useState('')

  // New Org
  const [orgOpen, setOrgOpen] = useState(false)
  const [orgForm, setOrgForm] = useState<NewOrgForm>(EMPTY_ORG)
  const [orgSaving, setOrgSaving] = useState(false)
  const [orgError, setOrgError] = useState<string | null>(null)

  // New Tenant
  const [tenantOpen, setTenantOpen] = useState(false)
  const [tenantForm, setTenantForm] = useState<NewTenantForm>(EMPTY_TENANT)
  const [tenantSaving, setTenantSaving] = useState(false)
  const [tenantError, setTenantError] = useState<string | null>(null)

  // Edit Tenant
  const [editing, setEditing] = useState<TenantRow | null>(null)
  const [editForm, setEditForm] = useState<EditTenantForm>({ display_name: '', idp_enabled: false, idp_domain: '', idp_client_id: '', idp_audience: '' })
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const orgsData = await organizationsApi.list()
      setOrgs(orgsData)
      const rows = (await Promise.all(
        orgsData.map(org =>
          tenantsApi.listByOrg(org.id)
            .then(ts => ts.map(t => ({ ...t, org_name: org.name } as TenantRow)))
            .catch(() => [] as TenantRow[])
        )
      )).flat()
      setTenants(rows)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadAll() }, [])

  const visible = filterOrgId ? tenants.filter(t => t.org_id === filterOrgId) : tenants

  async function submitOrg(e: React.FormEvent) {
    e.preventDefault()
    setOrgSaving(true); setOrgError(null)
    const body: CreateOrganizationRequest = {
      name: orgForm.name, slug: orgForm.slug,
      tenant: { tenant_id: orgForm.slug, display_name: orgForm.name, environment_type: 'production' },
    }
    try {
      await organizationsApi.create(body)
      setOrgOpen(false); setOrgForm(EMPTY_ORG); loadAll()
    } catch (e: unknown) { setOrgError(e instanceof Error ? e.message : 'Failed') }
    finally { setOrgSaving(false) }
  }

  async function submitTenant(e: React.FormEvent) {
    e.preventDefault()
    setTenantSaving(true); setTenantError(null)
    const body: CreateTenantRequest = {
      org_id: tenantForm.org_id, tenant_id: tenantForm.tenant_id,
      display_name: tenantForm.display_name, environment_type: tenantForm.environment_type,
      idp_config_override: idpFromForm(tenantForm),
    }
    try {
      await tenantsApi.create(body)
      setTenantOpen(false); setTenantForm(EMPTY_TENANT); loadAll()
    } catch (e: unknown) { setTenantError(e instanceof Error ? e.message : 'Failed') }
    finally { setTenantSaving(false) }
  }

  async function submitEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editing) return
    setEditSaving(true); setEditError(null)
    const body: UpdateTenantRequest = { display_name: editForm.display_name, idp_config_override: idpFromForm(editForm) }
    try {
      await tenantsApi.update(editing.tenant_id, body)
      setEditing(null); loadAll()
    } catch (e: unknown) { setEditError(e instanceof Error ? e.message : 'Failed') }
    finally { setEditSaving(false) }
  }

  function openEdit(t: TenantRow) {
    setEditing(t)
    setEditForm({
      display_name: t.display_name,
      idp_enabled: !!t.idp_config_override,
      idp_domain: t.idp_config_override?.domain ?? '',
      idp_client_id: t.idp_config_override?.client_id ?? '',
      idp_audience: t.idp_config_override?.audience ?? '',
    })
    setEditError(null)
  }

  async function doSuspend(t: TenantRow) {
    if (!window.confirm(`Suspend "${t.display_name}"?`)) return
    try { await tenantsApi.suspend(t.tenant_id); loadAll() }
    catch (e) { alert(e instanceof Error ? e.message : 'Failed') }
  }

  async function doReactivate(t: TenantRow) {
    if (!window.confirm(`Reactivate "${t.display_name}"?`)) return
    try { await tenantsApi.reactivate(t.tenant_id); loadAll() }
    catch (e) { alert(e instanceof Error ? e.message : 'Failed') }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
        <div className="flex gap-2">
          <button onClick={() => { setOrgForm(EMPTY_ORG); setOrgError(null); setOrgOpen(true) }}
            className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg hover:bg-gray-50">
            + New Organization
          </button>
          <button onClick={() => { setTenantForm({ ...EMPTY_TENANT, org_id: filterOrgId }); setTenantError(null); setTenantOpen(true) }}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700">
            + New Tenant
          </button>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-3">
        <span className="text-sm text-gray-500">Filter by organization:</span>
        <select value={filterOrgId} onChange={e => setFilterOrgId(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
          <option value="">All organizations</option>
          {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        {filterOrgId && <button onClick={() => setFilterOrgId('')} className="text-xs text-gray-400 hover:text-gray-600">Clear</button>}
      </div>

      {error && <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>}

      {loading ? (
        <div className="space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="animate-pulse bg-gray-200 rounded h-12 w-full" />)}</div>
      ) : visible.length === 0 ? (
        <p className="text-gray-500 text-sm">{tenants.length === 0 ? 'No tenants yet.' : 'No tenants match this filter.'}</p>
      ) : (
        <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
          <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3">Tenant ID</th>
              <th className="px-4 py-3">Display Name</th>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Environment</th>
              <th className="px-4 py-3">IdP</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {visible.map(t => (
              <tr key={t.tenant_id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-xs text-gray-500">{t.tenant_id}</td>
                <td className="px-4 py-3 font-medium text-gray-900">{t.display_name}</td>
                <td className="px-4 py-3 text-gray-500">{t.org_name}</td>
                <td className="px-4 py-3 text-gray-500">{t.environment_type}</td>
                <td className="px-4 py-3">
                  {t.idp_config_override
                    ? <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">configured</span>
                    : <span className="text-gray-300 text-xs">—</span>}
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                    t.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>{t.status}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button onClick={() => navigate(`/admin/tenant/users?tenantId=${t.tenant_id}`)}
                      className="text-xs px-2 py-1 bg-indigo-50 border border-indigo-200 rounded hover:bg-indigo-100 text-indigo-700 font-medium">
                      Manage →
                    </button>
                    <button onClick={() => openEdit(t)}
                      className="text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-100 text-gray-600">Edit</button>
                    {t.status === 'active'
                      ? <button onClick={() => doSuspend(t)} className="text-xs px-2 py-1 border border-red-200 rounded hover:bg-red-50 text-red-600">Suspend</button>
                      : t.status === 'suspended'
                      ? <button onClick={() => doReactivate(t)} className="text-xs px-2 py-1 border border-green-200 rounded hover:bg-green-50 text-green-600">Reactivate</button>
                      : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* New Organization Modal */}
      {orgOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-1">New Organization</h2>
            <p className="text-xs text-gray-400 mb-4">An initial tenant is created automatically using the slug as its ID.</p>
            {orgError && <div className="mb-3 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{orgError}</div>}
            <form onSubmit={submitOrg} className="space-y-4">
              <div>
                <label htmlFor="org-name" className="block text-sm font-medium text-gray-700 mb-1">Organization Name</label>
                <input id="org-name" type="text" required value={orgForm.name}
                  onChange={e => setOrgForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              </div>
              <div>
                <label htmlFor="org-slug" className="block text-sm font-medium text-gray-700 mb-1">Slug</label>
                <input id="org-slug" type="text" required value={orgForm.slug}
                  onChange={e => setOrgForm(f => ({ ...f, slug: e.target.value }))}
                  placeholder="e.g. acme"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                {orgForm.slug && <p className="mt-1 text-xs text-gray-400">Initial tenant ID: <span className="font-mono">{orgForm.slug}</span></p>}
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setOrgOpen(false)} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50">Cancel</button>
                <button type="submit" disabled={orgSaving} className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                  {orgSaving ? 'Creating…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* New Tenant Modal */}
      {tenantOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">New Tenant</h2>
            {tenantError && <div className="mb-3 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{tenantError}</div>}
            <form onSubmit={submitTenant} className="space-y-4">
              <div>
                <label htmlFor="nt-org" className="block text-sm font-medium text-gray-700 mb-1">Organization</label>
                <select id="nt-org" required value={tenantForm.org_id}
                  onChange={e => setTenantForm(f => ({ ...f, org_id: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
                  <option value="">Select an organization…</option>
                  {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="nt-tid" className="block text-sm font-medium text-gray-700 mb-1">Tenant ID</label>
                <input id="nt-tid" type="text" required value={tenantForm.tenant_id}
                  onChange={e => setTenantForm(f => ({ ...f, tenant_id: e.target.value }))}
                  placeholder="e.g. acme-prod"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                <p className="mt-1 text-xs text-gray-400">Cannot be changed after creation.</p>
              </div>
              <div>
                <label htmlFor="nt-dn" className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                <input id="nt-dn" type="text" required value={tenantForm.display_name}
                  onChange={e => setTenantForm(f => ({ ...f, display_name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              </div>
              <div>
                <label htmlFor="nt-env" className="block text-sm font-medium text-gray-700 mb-1">Environment Type</label>
                <select id="nt-env" value={tenantForm.environment_type}
                  onChange={e => setTenantForm(f => ({ ...f, environment_type: e.target.value as EnvType }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
                  {ENV_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <IdpFields prefix="nt" form={tenantForm} setForm={setTenantForm} />
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setTenantOpen(false)} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50">Cancel</button>
                <button type="submit" disabled={tenantSaving} className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                  {tenantSaving ? 'Creating…' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Tenant Modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold text-gray-900 mb-1">Edit Tenant</h2>
            <p className="text-xs font-mono text-gray-400 mb-4">{editing.tenant_id}</p>
            {editError && <div className="mb-3 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{editError}</div>}
            <form onSubmit={submitEdit} className="space-y-4">
              <div>
                <label htmlFor="edit-dn" className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                <input id="edit-dn" type="text" required value={editForm.display_name}
                  onChange={e => setEditForm(f => ({ ...f, display_name: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              </div>
              <IdpFields prefix="edit" form={editForm} setForm={setEditForm} />
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setEditing(null)} className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50">Cancel</button>
                <button type="submit" disabled={editSaving} className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                  {editSaving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
