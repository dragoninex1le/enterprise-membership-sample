// Supplier network — a buyer's tenant admin links their SupplierLink buyer account and decides
// which EMS role each SupplierLink contact role becomes. Suppliers then submit invoices into
// this tenant's payables through the supplier portal, without an EMS login.
import { useEffect, useState } from 'react'
import { usePorthContext } from '../context/PorthContext'
import { useHasRole } from '../hooks/useRoles'
import { PLATFORM_ADMIN } from '../constants'
import { roleTableOf, suppliersApi, type BuyerLink } from '../api/suppliers'
import { rolesApi } from '../api/roles'
import type { Role } from '../api/types'

type Row = { network: string; ems: string }

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
  const [mappingNote, setMappingNote] = useState<string | null>(null)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [working, setWorking] = useState(false)

  useEffect(() => {
    if (!tenantId || isPlatformAdmin) return
    suppliersApi.links().then(setLinks).catch(e => setMessage({ ok: false, text: messageOf(e) }))
    rolesApi.list(tenantId).then(all => setRoles(all.filter(r => !r.is_system))).catch(() => setRoles([]))
    suppliersApi
      .roleMapping(tenantId)
      .then(cfg => setRows(Object.entries(roleTableOf(cfg.mapping_source)).map(([network, ems]) => ({ network, ems }))))
      .catch(e => {
        const status = statusOf(e)
        setMappingNote(
          status === 404 ? 'No role mapping yet — every supplier contact will be refused until one exists.'
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
          Which EMS role a supplier contact gets, by the role SupplierLink gives them. Normally the EMS role is
          <span className="font-mono"> supplier</span>: submit invoices and follow their own.
        </p>
        {mappingNote && <p className="mb-3 text-sm text-amber-700">{mappingNote}</p>}
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
            }, 'Saved. Live supplier sessions pick it up on their next request.')}>
            Save roles
          </button>
        </div>
      </section>
    </div>
  )
}
