// The SupplierLink simulator API (supplierlink_sim/, its own stack). It plays SupplierLink:
// signs a supplier login with SupplierLink's key and trades it at EMS's
// POST /suppliers/session, which asks Porth's delegated mint for a token.
// No credentials: a plain cross-origin POST.

export type SignInMethod = 'role' | 'permissions'

export interface SignInForm {
  tenant: string
  buyer: string
  supplier: string
  contact: string
  method: SignInMethod
  role: string
  permissions: string
}

export interface SignInResult {
  /** Set when the simulator refused the form before signing or sending anything. */
  error?: string
  session_url?: string
  /** EMS's HTTP status for POST /suppliers/session. */
  status?: number
  /** How long EMS took to answer, measured by the simulator. */
  ems_ms?: number
  /** EMS's answer: token, session_id, expires_at, api_base_url, or an error code. */
  answer?: Record<string, unknown> | null
}

export function simulatorUrl(): string {
  return (import.meta.env.VITE_SUPPLIERLINK_SIM_URL ?? '').replace(/\/?$/, '/')
}

export async function signIn(form: SignInForm): Promise<SignInResult> {
  const base = import.meta.env.VITE_SUPPLIERLINK_SIM_URL
  if (!base) return { error: 'the simulator URL is not configured for this build (VITE_SUPPLIERLINK_SIM_URL)' }
  const reply = await fetch(`${simulatorUrl()}login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(form),
  })
  const body = await reply.json()
  // 400: the simulator refused the form before signing or sending anything ({detail}).
  if (!reply.ok) return { error: typeof body?.detail === 'string' ? body.detail : JSON.stringify(body) }
  return body as SignInResult
}
