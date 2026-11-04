// PORTH-128 — Flat tenant list with org filter, New Tenant (incl. IdP), Edit Tenant (incl. IdP)
//
// PORTH-595 — Announce: re-emit a tenant's lifecycle event so a service deployed after it can catch up
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { organizationsApi } from '../api/organizations'
import { tenantsApi } from '../api/tenants'
import { EMPTY_IDP, IdpFields, idpFormOf, idpFromForm, type IdpForm } from '../components/IdpFields'
import NewTenantWizard from '../components/NewTenantWizard'
import type { Organization, Tenant, UpdateTenantRequest } from '../api/types'

interface TenantRow extends Tenant { org_name: string }

interface EditTenantForm extends IdpForm {
  display_name: string
}

export default function TenantsPage() {
  const navigate = useNavigate()
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [tenants, setTenants] = useState<TenantRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterOrgId, setFilterOrgId] = useState('')

  // New Tenant
  const [tenantOpen, setTenantOpen] = useState(false)
  const [tenantWarning, setTenantWarning] = useState<string | null>(null)

  // Announce — re-emit a tenant's lifecycle event so consuming services that
  // were deployed after it existed can catch up (PORTH-595).
  const [announcing, setAnnouncing] = useState<string | null>(null)
  const [announced, setAnnounced] = useState<Record<string, string>>({})

  // Edit Tenant
  const [editing, setEditing] = useState<TenantRow | null>(null)
  const [editForm, setEditForm] = useState<EditTenantForm>({ ...EMPTY_IDP, display_name: '' })
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

  async function submitEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editing) return
    setEditSaving(true); setEditError(null)
    const body: UpdateTenantRequest = { display_name: editForm.display_name, idp_config_override: idpFromForm(editForm, editing.idp_config_override) }
    try {
      await tenantsApi.update(editing.tenant_id, body)
      setEditing(null); loadAll()
    } catch (e: unknown) { setEditError(e instanceof Error ? e.message : 'Failed') }
    finally { setEditSaving(false) }
  }

  /** Re-announce a tenant on the event plane, changing nothing about it.
   *
   * Consuming services keep read-only projections fed from the tenant-lifecycle
   * bus, and a service only ever hears about a tenant that changes AFTER it is
   * deployed. Every tenant that already existed is invisible to it — not
   * missing, never announced. Nothing reports that, because from the bus's point
   * of view nothing has happened.
   *
   * This sends the tenant's CURRENT display_name back unchanged. Porth's
   * tenant_repo publishes `tenant.updated` on every update without checking
   * whether anything differs, so a no-op write is a real event on the wire, and
   * a consumer that provisions on `updated` catches up. That the payload is
   * unchanged is the point: an operator should not have to edit a live tenant to
   * make a downstream service notice it.
   */
  async function doAnnounce(t: TenantRow) {
    setAnnouncing(t.tenant_id)
    // Clear any previous result for this row. Written as a filter rather than
    // rest-destructuring with a discarded binding: tsconfig sets
    // noUnusedLocals, so `const { [id]: _drop, ...rest }` fails the build.
    setAnnounced(a => Object.fromEntries(Object.entries(a).filter(([id]) => id !== t.tenant_id)))
    try {
      await tenantsApi.update(t.tenant_id, { display_name: t.display_name })
      setAnnounced(a => ({ ...a, [t.tenant_id]: 'announced' }))
    } catch (e: unknown) {
      setAnnounced(a => ({ ...a, [t.tenant_id]: e instanceof Error ? e.message : 'Failed' }))
    } finally {
      setAnnouncing(null)
    }
  }

  function openEdit(t: TenantRow) {
    setEditing(t)
    setEditForm({
      display_name: t.display_name,
      ...idpFormOf(t.idp_config_override),
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
          <button onClick={() => setTenantOpen(true)}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700">
            + New Tenant
          </button>
        </div>
      </div>

      {tenantWarning && <div role="alert" className="mb-4 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-800">{tenantWarning}</div>}

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
              <th className="px-4 py-3">Tier</th>
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
                <td className="px-4 py-3 text-gray-500">{t.tenant_tier}</td>
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
                    <button onClick={() => navigate(`/admin/tenant/claim-config?tenantId=${t.tenant_id}`)}
                      className="text-xs px-2 py-1 bg-indigo-50 border border-indigo-200 rounded hover:bg-indigo-100 text-indigo-700 font-medium">
                      Manage →
                    </button>
                    <button onClick={() => openEdit(t)}
                      className="text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-100 text-gray-600">Edit</button>
                    <button onClick={() => doAnnounce(t)} disabled={announcing === t.tenant_id}
                      title="Re-emit this tenant's lifecycle event so consuming services can catch up. Changes nothing about the tenant."
                      className="text-xs px-2 py-1 border border-indigo-200 rounded hover:bg-indigo-50 text-indigo-700 disabled:opacity-50">
                      {announcing === t.tenant_id ? 'Announcing…' : 'Announce'}
                    </button>
                    {announced[t.tenant_id] && (
                      <span className={`text-xs ${announced[t.tenant_id] === 'announced' ? 'text-green-600' : 'text-red-600'}`}>
                        {announced[t.tenant_id] === 'announced' ? '✓ on the bus' : announced[t.tenant_id]}
                      </span>
                    )}
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

      {tenantOpen && (
        <NewTenantWizard orgs={orgs} initialOrgId={filterOrgId} onClose={warning => {
          setTenantOpen(false)
          setTenantWarning(warning)
          loadAll()
        }} />
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
