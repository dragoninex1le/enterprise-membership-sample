import { Fragment, useEffect, useState } from 'react'
import { sampleApiClient } from '../api/sampleApp'
import { usePorthContext } from '../context/PorthContext'
import { PERMISSIONS } from '../constants'
import Fingerprint, { hasFingerprint, type FingerprintFields } from '../components/Fingerprint'

interface Approval extends FingerprintFields {
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

interface Attempt {
  attempt: string
  expect: 'allow' | 'deny'
  allowed: boolean
  detail: string
  /** How many DISTINCT tenant partitions the read returned. One is this tenant;
   *  anything above one is a breach, which is why it is a number on screen and
   *  not left to be inferred. */
  partitions_seen: number
  pass: boolean
}

interface FfugProbe {
  ok: boolean
  error?: string
  table?: string
  environment?: string
  tenant_id?: string
  probe_tenant?: string | null
  role?: string | null
  attempts?: Attempt[]
  isolated?: boolean
}

interface Identity {
  tenant_id: string
  narrowed: boolean
  app_table: string
  role: string | null
  probes: Probe[]
  isolated: boolean
  ffug?: FfugProbe
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

// PORTH-599 — the same boundary, on the other plane.
//
// The strip above runs on credentials the AUTHORIZER minted for this browser
// session. This one runs on credentials ffug narrowed for ITSELF, from a signed
// envelope, with no authorizer in the path at all — which is the case the ffug
// fixture exists to demonstrate and the only one that speaks to service-to-
// service isolation.
//
// The first row is the one to read. "Scan the whole table" is expected to be
// REFUSED, and that is not a limitation being apologised for: dynamodb:LeadingKeys
// binds to the key of the item being accessed, and a scan names no key, so the
// condition would pass vacuously and hand back EVERY tenant's rows. A scan
// cannot be narrowed. So ffug is granted none, and the proof is that it cannot
// ask the question rather than that it asked and was given only its share.
function FfugStrip({
  ffug,
  onProbe,
}: {
  ffug?: FfugProbe
  onProbe: (tenant: string) => void
}) {
  const [named, setNamed] = useState('')
  if (!ffug) return null
  if (!ffug.ok) {
    return (
      <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        <span className="font-semibold">ffug (internal plane): </span>
        unreachable — {ffug.error}
      </div>
    )
  }
  const ok = ffug.isolated
  return (
    <div
      className={`mb-4 rounded-md border px-3 py-2 text-xs ${
        ok ? 'border-green-200 bg-green-50 text-green-900'
           : 'border-red-200 bg-red-50 text-red-900'
      }`}
    >
      <div>
        <span className="font-semibold">ffug narrowed itself to: </span>
        <span className="font-mono">{ffug.role ?? 'unknown'}</span>
        <span className="mx-2 text-gray-400">|</span>
        <span className="font-semibold">table: </span>
        <span className="font-mono">{ffug.table}</span>
        <span className="mx-2 text-gray-400">|</span>
        <span className="font-semibold">tenant: </span>
        <span className="font-mono">{ffug.tenant_id}</span>
        <span className="ml-2 opacity-70">(from the envelope — the call carried no tenant field)</span>
      </div>
      <table className="mt-2 font-mono text-[11px]">
        <tbody>
          {(ffug.attempts ?? []).map(a => (
            <tr key={a.attempt}>
              <td className="pr-3">{a.pass ? '\u2713' : '\u2717'}</td>
              <td className="pr-3">{a.attempt}</td>
              <td className="pr-3 opacity-70">expected {a.expect}</td>
              <td className="pr-3 opacity-70">{a.detail}</td>
              <td className="opacity-70">
                {a.allowed ? `${a.partitions_seen} tenant partition(s) seen` : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-1">
        {ok
          ? 'ffug cannot scan its own table at all, and can query only the partition its envelope names. Nothing in the call said which tenant \u2014 there is no field in which it could have.'
          : 'NOT isolated \u2014 a read that should have been refused was allowed, or ffug\u2019s own partition was not readable. Check the row that failed.'}
      </div>
      {/* The refusals above all target a tenant invented for the purpose. IAM
          denies on the key before consulting data, so they are honest, but they
          cannot show a reader the difference between "refused" and "empty
          anyway". Naming a tenant that really exists can. The value scopes
          nothing: ffug still takes the tenant it SERVES from the envelope, and
          this only builds a partition the probe asserts must be refused. */}
      <div className="mt-2 flex items-center gap-2">
        <span className="text-gray-500">Refuse me a real tenant:</span>
        <input
          value={named}
          onChange={e => setNamed(e.target.value)}
          placeholder="another tenant id"
          className="rounded border border-gray-300 px-1.5 py-0.5 font-mono text-[11px]"
        />
        <button
          onClick={() => onProbe(named.trim())}
          disabled={!named.trim()}
          className="rounded bg-gray-200 px-2 py-0.5 text-[11px] font-medium text-gray-800 hover:bg-gray-300 disabled:opacity-40"
        >
          Try to read it
        </button>
        {ffug.probe_tenant && (
          <span className="text-gray-500">last probed {ffug.probe_tenant}</span>
        )}
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

    loadIdentity()
  }, [currentUser])

  // Best effort, and deliberately not awaited with the list: a diagnostic that
  // can break the page it diagnoses is worse than no diagnostic.
  function loadIdentity(probeTenant = '') {
    sampleApiClient
      .get<Identity>('/sample/diagnostics/identity', {
        params: probeTenant ? { probe_tenant: probeTenant } : undefined,
      })
      .then(r => setIdentity(r.data))
      .catch(() => setIdentity(null))
  }

  // PORTH-621 — watch the rows whose answer has not arrived.
  //
  // Polled per RECORD rather than by refetching the list, and that is forced
  // rather than preferred: /sample/approvals returns what awaits a decision, so
  // an approved record leaves it the moment it is approved. Refetching would
  // drop the very rows being watched.
  //
  // Keyed on a joined string, not the array. `approvals` is a new object on
  // every merge, so an array dependency would tear down and rebuild the
  // interval on each tick and it would never fire.
  const queuedKeys = approvals
    .filter(a => a.fingerprint_status === 'queued')
    .map(a => `${a.record_type}/${a.record_id}`)
    .join(',')

  useEffect(() => {
    if (!queuedKeys) return
    const keys = queuedKeys.split(',')
    const poll = () => {
      keys.forEach(key => {
        sampleApiClient
          .get<Approval>(`/sample/approvals/${key}`)
          .then(r => {
            if (r.data?.fingerprint_status !== 'complete') return
            setApprovals(prev =>
              prev.map(a =>
                `${a.record_type}/${a.record_id}` === key ? { ...a, ...r.data } : a
              )
            )
          })
          // Swallowed on purpose. A poll that fails is a poll that tries again;
          // surfacing it in the page-level error banner would replace the
          // approval list with a transient network message.
          .catch(() => {})
      })
    }
    const id = window.setInterval(poll, 3000)
    return () => window.clearInterval(id)
  }, [queuedKeys])

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
                  fingerprint_status: r.data.fingerprint_status,
                  fingerprint_trace_id: r.data.fingerprint_trace_id,
                  fingerprint_correlation_hash: r.data.fingerprint_correlation_hash,
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
      <FfugStrip ffug={identity?.ffug} onProbe={loadIdentity} />
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
                {hasFingerprint(appr) && (
                  <tr className="bg-gray-50/60">
                    <td colSpan={canWrite ? 8 : 7} className="px-4 pb-3 pt-0">
                      <Fingerprint record={appr} />
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
