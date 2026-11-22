// Supplier network — a buyer's tenant admin links their SupplierLink buyer account and decides
// which EMS role a SupplierLink contact gets: by the contact's SupplierLink role, or by the
// contact's SupplierLink permissions (the role holding exactly what they mean). Both are
// Porth's claim-mapping routes and EMS keeps both testable. Suppliers then submit invoices
// into this tenant's payables through the supplier portal, without an EMS login.
import { useEffect, useState } from 'react'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'
import { methodOf, permissionTableOf, roleTableOf, suppliersApi, type BuyerLink, type MappingMethod } from '../api/suppliers'
import { rolesApi } from '../api/roles'
import { permissionsApi } from '../api/permissions'
import type { Permission, Role } from '../api/types'

type Row = { network: string; ems: string }
type PermissionRow = { network: string; ems: string[] }

const card = 'rounded-lg border border-gray-200 bg-white p-5 mb-6'
const field = 'rounded-md border border-gray-300 px-3 py-1.5 text-sm'
const primary = 'rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50'

const statusOf = (e: unknown): number | undefined => (e as { response?: { status?: number } })?.response?.status
const messageOf = (e: unknown): string => (e instanceof Error ? e.message : String(e))

/** The value Porth's resolve_roles needs to reach a role: its source key, or its name. */
const roleKey = (role: Role): string =>
  (Array.isArray(role.source_key) ? role.source_key[0] : role.source_key) || role.name

export default function SupplierNetworkPage() {
  const { currentUser } = usePorthContext()
  const isPlatformAdmin = useHasRole(PLATFORM_ADMIN)
  const tenantId = currentUser?.porthUser.tenant_id ?? ''

  const [links, setLinks] = useState<BuyerLink[]>([])
  const [buyer, setBuyer] = useState('')
  const [roles, setRoles] = useState<Role[]>([])
  const [rows, setRows] = useState<Row[]>([])
  const [method, setMethod] = useState<MappingMethod>('role')
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [permissionRows, setPermissionRows] = useState<PermissionRow[]>([])
  const [mappingNote, setMappingNote] = useState<string | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [working, setWorking] = useState(false)

  useEffect(() => {
    if (!tenantId || isPlatformAdmin) return
    suppliersApi.links().then(setLinks).catch(e => setMessage({ ok: false, text: messageOf(e) }))
    rolesApi.list(tenantId).then(all => setRoles(all.filter(r => !r.is_system))).catch(() => setRoles([]))
    permissionsApi.list(tenantId).then(setPermissions).catch(() => setPermissions([]))
    suppliersApi
      .roleMapping(tenantId)
      .then(cfg => {
        setMethod(methodOf(cfg.mapping_source))
        setRows(Object.entries(roleTableOf(cfg.mapping_source)).map(([network, ems]) => ({ network, ems })))
        setPermissionRows(
          Object.entries(permissionTableOf(cfg.mapping_source)).map(([network, ems]) => ({ network, ems })),
        )
      })
      .catch(e => {
        const status = statusOf(e)
        setMappingNote(
          status === 404 ? 'No mapping yet — every supplier contact will be refused until one exists.'
            : status === 403 ? 'Porth did not show this mapping to your session (it needs tenant.claim_mappings.manage).'
              : messageOf(e),
        )
      })
  }, [tenantId, isPlatformAdmin])

  if (isPlatformAdmin) {
    return (
      <div className={card}>
        <h1 className="text-xl font-semibold">Supplier network</h1>
        <p className="mt-2 text-sm text-gray-600">
          A buyer account is linked by that buyer's own tenant administrator, so supplier sessions are issued in the
          tenant that linked it.
        </p>
      </div>
    )
  }

  const attempt = async (work: () => Promise<void>, done: string) => {
    setWorking(true)
    setMessage(null)
    try {
      await work()
      setMessage({ ok: true, text: done })
    } catch (e) {
      setMessage({ ok: false, text: messageOf(e) })
    } finally {
      setWorking(false)
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Supplier network</h1>
        <p className="mt-1 text-sm text-gray-500">
          Your suppliers sign in to SupplierLink, not to EMS. Link your SupplierLink buyer account and they can submit
          invoices straight into your payables and follow them through approval — seeing only their own.
        </p>
      </div>

      {message && (
        <div className={`mb-4 rounded-md border px-4 py-3 text-sm ${message.ok ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-700'}`}>
          {message.text}
        </div>
      )}

      <section className={card} aria-label="Buyer account">
        <h2 className="text-lg font-semibold mb-3">Buyer account</h2>
        {links.length === 0 ? (
          <p className="mb-3 text-sm text-gray-500">Not linked.</p>
        ) : (
          <ul className="mb-4 divide-y divide-gray-100">
            {links.map(l => (
              <li key={l.buyer} className="flex items-center justify-between py-2 text-sm">
                <span><span className="font-mono">{l.buyer}</span> <span className="text-gray-500">linked {new Date(l.linked_at).toLocaleString()}</span></span>
                <button
                  className="text-sm text-red-600" disabled={working}
                  onClick={() => attempt(async () => { await suppliersApi.unlink(l.buyer); setLinks(await suppliersApi.links()) },
                    `Unlinked ${l.buyer}. New supplier sessions are refused; existing ones run until they expire.`)}
                >
                  Unlink
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <input className={field} aria-label="SupplierLink buyer account id" placeholder="SupplierLink buyer account id"
            value={buyer} onChange={e => setBuyer(e.target.value)} />
          <button className={primary} disabled={working || !buyer.trim()}
            onClick={() => attempt(async () => { await suppliersApi.link(buyer.trim()); setLinks(await suppliersApi.links()); setBuyer('') }, 'Linked.')}>
            Link
          </button>
        </div>
      </section>

      <section className={card} aria-label="Supplier roles">
        <h2 className="mb-1 text-lg font-semibold">Supplier roles</h2>
        <p className="mb-3 text-sm text-gray-500">
          Which EMS role a supplier contact gets. Normally the EMS role is
          <span className="font-mono"> supplier</span>: submit invoices and follow their own. Saving one method
          replaces the other; sessions minted after a save use it.
        </p>
        {mappingNote && <p className="mb-3 text-sm text-amber-700">{mappingNote}</p>}
        <fieldset className="mb-4 flex gap-6 text-sm" aria-label="Match supplier contacts by">
          <label className="flex items-center gap-2">
            <input type="radio" name="method" checked={method === 'role'} onChange={() => setMethod('role')} />
            By SupplierLink role
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="method" checked={method === 'permissions'} onChange={() => setMethod('permissions')} />
            By SupplierLink permissions
          </label>
        </fieldset>

        {method === 'role' ? (
          <>
            <table className="mb-3 text-sm">
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td className="py-1 pr-2">
                      <input className={field} aria-label="SupplierLink role" value={row.network}
                        onChange={e => setRows(rows.map((r, j) => (j === i ? { ...r, network: e.target.value } : r)))} />
                    </td>
                    <td className="pr-2">becomes</td>
                    <td className="pr-2">
                      <select className={field} aria-label="EMS role" value={row.ems}
                        onChange={e => setRows(rows.map((r, j) => (j === i ? { ...r, ems: e.target.value } : r)))}>
                        <option value="">Choose a role</option>
                        {roles.map(role => <option key={role.id} value={roleKey(role)}>{role.name}</option>)}
                      </select>
                    </td>
                    <td>
                      <button className="text-gray-500" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2">
              <button className="rounded-md border border-gray-300 px-3 py-1.5 text-sm" onClick={() => setRows([...rows, { network: '', ems: '' }])}>
                Add a SupplierLink role
              </button>
              <button className={primary} disabled={working}
                onClick={() => attempt(async () => {
                  await suppliersApi.saveRoleMapping(tenantId, Object.fromEntries(rows.map(r => [r.network, r.ems])))
                  setMappingNote(null)
                }, 'Saved. Supplier sessions minted from now on use it.')}>
                Save roles
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="mb-3 text-sm text-gray-500">
              What each SupplierLink permission means in EMS. A contact gets the role whose permissions are
              <em> exactly</em> what their SupplierLink permissions mean, or no session at all. A SupplierLink
              permission not listed here means nothing.
            </p>
            <table className="mb-3 text-sm">
              <tbody>
                {permissionRows.map((row, i) => (
                  <tr key={i} className="align-top">
                    <td className="py-1 pr-2">
                      <input className={field} aria-label="SupplierLink permission" value={row.network}
                        onChange={e => setPermissionRows(permissionRows.map((r, j) => (j === i ? { ...r, network: e.target.value } : r)))} />
                    </td>
                    <td className="py-1 pr-2">means</td>
                    <td className="py-1 pr-2">
                      <select multiple className={field} aria-label="EMS permissions" value={row.ems}
                        onChange={e => {
                          const chosen = Array.from(e.target.selectedOptions, o => o.value)
                          setPermissionRows(permissionRows.map((r, j) => (j === i ? { ...r, ems: chosen } : r)))
                        }}>
                        {permissions.map(p => <option key={p.id} value={p.key}>{p.key}</option>)}
                      </select>
                    </td>
                    <td className="py-1">
                      <button className="text-gray-500" onClick={() => setPermissionRows(permissionRows.filter((_, j) => j !== i))}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2">
              <button className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
                onClick={() => setPermissionRows([...permissionRows, { network: '', ems: [] }])}>
                Add a SupplierLink permission
              </button>
              <button className={primary} disabled={working}
                onClick={() => attempt(async () => {
                  await suppliersApi.savePermissionMapping(tenantId, Object.fromEntries(permissionRows.map(r => [r.network, r.ems])))
                  setMappingNote(null)
                }, 'Saved. Supplier sessions minted from now on use it.')}>
                Save permissions
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
