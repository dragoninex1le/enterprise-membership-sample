import { Fragment, useEffect, useState } from 'react'
import { sampleApiClient } from '../api/sampleApp'
import { usePorthContext } from '../context/PorthContext'
import { PERMISSIONS } from '../constants'

interface Approval {
  record_id: string
  /** 'invoice' | 'bill' — which record this is, and which endpoint decides it.
   *  PORTH-597: an approval IS an invoice or a bill, so the type is needed to
   *  address it. It was `type` before, against an API that returned nothing. */
  record_type: string
  counterparty: string
  amount: string
  submitted_by: string
  submitted_at: string
  status: string
  /** PORTH-599 — ffug's answer, present once a decision has been fingerprinted.
   *  The prime is the tenant's own, minted from the bus and readable by nothing
   *  else; the digest is SHA256(prime : document). Empty is a real state, not a
   *  blank: the record predates the fingerprint, or ffug was unreachable. */
  fingerprint_prime?: string
  fingerprint_digest?: string
  /** Returned by the approve call only — what was hashed, so the number on the
   *  screen can be checked by hand rather than believed. */
  fingerprint_document?: Record<string, string>
  fingerprint_error?: string
}

const STATUS_BADGE: Record<string, string> = {
  // The status is on the record itself now, so it is the record's word for it:
  // `pending_approval`, not a separate approval row's `pending` (PORTH-597).
  pending_approval: 'bg-yellow-100 text-yellow-800',
  pending: 'bg-yellow-100 text-yellow-800',
  approved: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_BADGE[status] ?? 'bg-gray-100 text-gray-800'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

interface Probe {
  partition: string
  expect: 'allow' | 'deny'
  allowed: boolean
  detail: string
  pass: boolean
}

interface Identity {
  tenant_id: string
  narrowed: boolean
  app_table: string
  role: string | null
  probes: Probe[]
  isolated: boolean
}

// Shows what the request was REFUSED, not only what it could read.
//
// The first version of this reported a successful read and called it proof. It
// was not: reading your own data shows the credentials work and says nothing
// about what is kept out, which is the whole property. The role name now comes
// from sts:GetCallerIdentity rather than being inferred, and two deliberately
// forbidden reads are attempted on every load.
function IdentityStrip({ identity }: { identity: Identity | null }) {
  if (!identity) return null
  const ok = identity.isolated
  return (
    <div
      className={`mb-4 rounded-md border px-3 py-2 text-xs ${
        ok ? 'border-green-200 bg-green-50 text-green-900'
           : 'border-amber-200 bg-amber-50 text-amber-900'
      }`}
    >
      <div>
        <span className="font-semibold">Served as: </span>
        <span className="font-mono">{identity.role ?? 'unknown'}</span>
        <span className="mx-2 text-gray-400">|</span>
        <span className="font-semibold">tenant: </span>
        <span className="font-mono">{identity.tenant_id}</span>
        <span className="mx-2 text-gray-400">|</span>
        <span>{identity.narrowed ? 'narrowed credentials' : 'ambient identity'}</span>
      </div>
      <table className="mt-2 font-mono text-[11px]">
        <tbody>
          {identity.probes.map(probe => (
            <tr key={probe.partition}>
              <td className="pr-3">{probe.pass ? '\u2713' : '\u2717'}</td>
              <td className="pr-3">{probe.partition}</td>
              <td className="pr-3 opacity-70">expected {probe.expect}</td>
              <td className="opacity-70">{probe.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1">
        {ok
          ? 'Isolated: this tenant\u2019s partition is readable and every forbidden one \u2014 another tenant, a name-extension of this one, and another environment \u2014 is refused by IAM.'
          : 'NOT isolated on the evidence above \u2014 a read that should have been refused was allowed, or the tenant\u2019s own read failed.'}
      </div>
    </div>
  )
}

// PORTH-599 — what ffug said, and what it said it about.
//
// Shown as the document AND the prime AND the result rather than just a hash,
// because a bare digest proves nothing to the person looking at it. With all
// three on screen you can recompute it yourself, and the claim being made is
// checkable: this tenant's prime produced this number from this document, and
// no other tenant's could, because ffug serving them cannot read this prime.
function Fingerprint({ appr }: { appr: Approval }) {
  if (appr.fingerprint_error) {
    return (
      <div className="text-xs text-amber-700">
        approved, but not fingerprinted — {appr.fingerprint_error}
      </div>
    )
  }
  if (!appr.fingerprint_digest) return null
  return (
    <div className="space-y-0.5 font-mono text-[11px] text-gray-600">
      {appr.fingerprint_document && (
        <div>
          <span className="text-gray-400">document </span>
          {JSON.stringify(appr.fingerprint_document)}
        </div>
      )}
      <div>
        <span className="text-gray-400">primed with </span>
        {appr.fingerprint_prime}
        <span className="text-gray-400"> (this tenant\u2019s, from the bus)</span>
      </div>
      <div>
        <span className="text-gray-400">sha256 </span>
        {appr.fingerprint_digest}
      </div>
    </div>
  )
}

export default function ApprovalsPage() {
  const { currentUser } = usePorthContext()
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const canWrite = currentUser?.permissions?.includes(PERMISSIONS.APPROVALS_WRITE) ?? false

  useEffect(() => {
    if (!currentUser) return
    setLoading(true)
    setError(null)
    sampleApiClient
      .get<Approval[]>('/sample/approvals')
      .then(r => {
        // Guard the shape, not just the status. CloudFront used to rewrite API
        // 403s and 404s into 200 + index.html, so this resolved with an HTML
        // STRING and the render crashed on `.map` — an error that named the
        // component and nothing about the actual failure. The rewrite is gone
        // (PORTH-586), and this makes the same mistake impossible to repeat
        // silently from any other cause.
        if (!Array.isArray(r.data)) {
          throw new Error(
            'expected a list of approvals, received ' + typeof r.data +
            ' — the API returned something that is not this endpoint\u2019s response'
          )
        }
        setApprovals(r.data)
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))

    // Best effort, and deliberately not awaited with the list: a diagnostic
    // that can break the page it diagnoses is worse than no diagnostic.
    sampleApiClient
      .get<Identity>('/sample/diagnostics/identity')
      .then(r => setIdentity(r.data))
      .catch(() => setIdentity(null))
  }, [currentUser])

  function handleAction(appr: Approval, action: 'approve' | 'reject') {
    const recordId = appr.record_id
    sampleApiClient
      .post<Approval>(`/sample/approvals/${appr.record_type}/${recordId}/${action}`)
      .then(r => {
        setApprovals(prev =>
          prev.map(a =>
            a.record_id === recordId
              ? {
                  ...a,
                  status: r.data.status ?? (action === 'approve' ? 'approved' : 'rejected'),
                  fingerprint_prime: r.data.fingerprint_prime,
                  fingerprint_digest: r.data.fingerprint_digest,
                  fingerprint_document: r.data.fingerprint_document,
                  fingerprint_error: r.data.fingerprint_error,
                }
              : a
          )
        )
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Approvals</h1>
      <IdentityStrip identity={identity} />
      <p className="text-sm text-gray-500 mb-6">Review and approve/reject transactions — Controllers only</p>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-8 space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-6 bg-gray-200 rounded animate-pulse" />
            ))}
          </div>
        ) : approvals.length === 0 ? (
          <div className="p-8 text-center text-gray-400 text-sm">No pending approvals</div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                {[
                  'Record ID', 'Type', 'For', 'Amount', 'Submitted By', 'Date', 'Status',
                  ...(canWrite ? ['Actions'] : []),
                ].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {approvals.map(appr => (
                <Fragment key={appr.record_id}>
                <tr className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-mono text-gray-500">{appr.record_id.slice(0, 8)}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 capitalize">{appr.record_type}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{appr.counterparty || '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">£{parseFloat(appr.amount).toFixed(2)}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{appr.submitted_by}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {appr.submitted_at ? new Date(appr.submitted_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={appr.status} /></td>
                  {canWrite && (
                    <td className="px-4 py-3">
                      {appr.status === 'pending_approval' && (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleAction(appr, 'approve')}
                            className="rounded px-2.5 py-1 text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200"
                          >
                            Approve
                          </button>
                          <button
                            onClick={() => handleAction(appr, 'reject')}
                            className="rounded px-2.5 py-1 text-xs font-medium bg-red-100 text-red-800 hover:bg-red-200"
                          >
                            Reject
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
                {(appr.fingerprint_digest || appr.fingerprint_error) && (
                  <tr className="bg-gray-50/60">
                    <td colSpan={canWrite ? 8 : 7} className="px-4 pb-3 pt-0">
                      <Fingerprint appr={appr} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
