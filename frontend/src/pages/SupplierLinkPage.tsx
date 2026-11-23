// SupplierLink sign-in — a test page that plays the supplier network. It is outside the
// EMS app: no EMS login, no tenant configuration, no Porth session (main.tsx renders it
// before any of that). It calls the SupplierLink simulator API, which signs the supplier's
// login and trades it at EMS for a Porth token, and shows what EMS answered.
//
// Every control has a label (prawf finds controls by role and name) and a data-prawfid,
// which is how prawf builds the control manifest.
import { useState, type FormEvent } from 'react'
import { signIn, type SignInForm, type SignInResult } from '../api/supplierLinkSim'

const card = 'rounded-lg border border-gray-200 bg-white p-5 mb-6'
const field = 'w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm'
const label = 'block text-sm font-medium text-gray-700 mb-1'
const primary = 'rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50'

/** The tenant this page's host names: acme.{slot}.{zone} → acme. The platform apex names none. */
function tenantOfHost(): string {
  const first = window.location.hostname.split('.')[0]
  return first && first !== import.meta.env.VITE_PLATFORM_APEX && first !== 'localhost' ? first : 'ems-test'
}

export default function SupplierLinkPage() {
  const [form, setForm] = useState<SignInForm>({
    tenant: tenantOfHost(),
    buyer: 'buyer-ems-test',
    supplier: 'proof-sup-a',
    contact: 'contact-a',
    method: 'role',
    role: 'billing',
    permissions: 'invoices:submit, invoices:view',
  })
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<SignInResult | null>(null)
  const [failure, setFailure] = useState('')

  const set = (name: keyof SignInForm) => (e: { target: { value: string } }) =>
    setForm({ ...form, [name]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setResult(null)
    setFailure('')
    try {
      setResult(await signIn(form))
    } catch (err) {
      setFailure(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const token = typeof result?.answer?.token === 'string' ? result.answer.token : ''
  const status = result?.error ? `not sent: ${result.error}` : result?.status ?? (failure ? `failed: ${failure}` : '-')

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-2xl">
        <h1 className="text-xl font-semibold text-gray-900 mb-1">SupplierLink sign-in</h1>
        <p className="text-sm text-gray-500 mb-6">
          Plays the supplier network: signs a supplier's login and trades it at EMS for a Porth token.
        </p>

        <form className={card} onSubmit={submit} aria-label="Supplier sign-in" data-prawfid="signin.form">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={label} htmlFor="tenant">Buyer tenant</label>
              <input id="tenant" className={field} value={form.tenant} onChange={set('tenant')}
                     data-prawfid="signin.form.tenant" />
            </div>
            <div>
              <label className={label} htmlFor="buyer">SupplierLink buyer account</label>
              <input id="buyer" className={field} value={form.buyer} onChange={set('buyer')}
                     data-prawfid="signin.form.buyer" />
            </div>
            <div>
              <label className={label} htmlFor="supplier">Supplier</label>
              <input id="supplier" className={field} value={form.supplier} onChange={set('supplier')}
                     data-prawfid="signin.form.supplier" />
            </div>
            <div>
              <label className={label} htmlFor="contact">Contact</label>
              <input id="contact" className={field} value={form.contact} onChange={set('contact')}
                     data-prawfid="signin.form.contact" />
            </div>
          </div>

          <fieldset className="mt-5">
            <legend className={label}>What SupplierLink says about them</legend>
            <div className="flex gap-6 text-sm mb-3">
              <label className="flex items-center gap-2">
                <input type="radio" name="method" value="role" checked={form.method === 'role'}
                       onChange={() => setForm({ ...form, method: 'role' })} data-prawfid="signin.form.by-role" />
                By role
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="method" value="permissions" checked={form.method === 'permissions'}
                       onChange={() => setForm({ ...form, method: 'permissions' })}
                       data-prawfid="signin.form.by-permissions" />
                By permissions
              </label>
            </div>
            {form.method === 'role' ? (
              <div>
                <label className={label} htmlFor="role">SupplierLink role</label>
                <input id="role" className={field} value={form.role} onChange={set('role')}
                       data-prawfid="signin.form.role" />
              </div>
            ) : (
              <div>
                <label className={label} htmlFor="permissions">SupplierLink permissions (comma-separated)</label>
                <input id="permissions" className={field} value={form.permissions} onChange={set('permissions')}
                       data-prawfid="signin.form.permissions" />
              </div>
            )}
          </fieldset>

          <button type="submit" className={`${primary} mt-5`} disabled={busy} data-prawfid="signin.form.sign-in">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <section className={card} aria-label="Result">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Result</h2>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
            <dt className="text-gray-500">Status</dt>
            <dd data-prawfid="signin.result.status">{String(status)}</dd>
            <dt className="text-gray-500">EMS took</dt>
            <dd data-prawfid="signin.result.ems-ms">{result?.ems_ms !== undefined ? `${result.ems_ms} ms` : '-'}</dd>
            <dt className="text-gray-500">Token</dt>
            <dd className="font-mono break-all" data-prawfid="signin.result.token">{token || '-'}</dd>
          </dl>
          <h3 className="text-sm font-semibold text-gray-900 mt-4 mb-2">EMS answered</h3>
          <pre className="rounded bg-gray-100 p-3 text-xs whitespace-pre-wrap break-all" data-prawfid="signin.result.answer">
            {result ? JSON.stringify(result.answer ?? result, null, 2) : '-'}
          </pre>
        </section>
      </div>
    </div>
  )
}
