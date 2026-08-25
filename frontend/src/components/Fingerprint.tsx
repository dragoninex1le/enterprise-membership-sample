/**
 * What ffug said about a decision, and what we committed to before asking.
 *
 * Shared by ApprovalsPage, ARPage and APPage rather than written three times.
 * The reason is not brevity — it is that the LABELS carry the meaning here, and
 * three copies would drift into three different accounts of what these numbers
 * are (PORTH-622).
 *
 * ## The two hashes are different things
 *
 * A screen showing them adjacent invites the reading that they should be equal.
 * They never are:
 *
 *   H (correlation)  identifies WHICH REQUEST. SHA256 over
 *                    (environment, tenant_id, "sample-app", trace_id).
 *                    Written at APPROVAL, before ffug is asked for anything.
 *
 *   digest           identifies WHAT WAS HASHED. SHA256(prime : document).
 *                    Written at CALLBACK, from ffug's answer.
 *
 * So H is labelled by WHEN it was committed, because that ordering is the whole
 * mechanism: a hash produced after the answer arrived would be derived from the
 * answer and would match itself. And "matched" is rendered as a STATE rather
 * than as two strings a reader is meant to compare — the comparison happened
 * server-side, between H and Porth's recomputation of H from the callback's
 * verified claims.
 *
 * Neither value is sensitive. The prime is not a secret (see ffug's salt.py),
 * and H is a digest over an environment, a tenant, a fixed service id and a
 * trace already shown beside it.
 */

export interface FingerprintFields {
  /** 'queued' | 'complete' | absent. Absent is REAL: the record predates ffug,
   *  or ffug was unreachable, and no answer is coming. Rendering that as
   *  'queued' would promise something that never arrives. */
  fingerprint_status?: string
  fingerprint_trace_id?: string
  fingerprint_correlation_hash?: string
  fingerprint_prime?: string
  fingerprint_digest?: string
  /** Returned by the approve call only — what was hashed, so the digest on the
   *  screen can be checked by hand rather than believed. */
  fingerprint_document?: Record<string, string>
  fingerprint_error?: string
}

export function hasFingerprint(record: FingerprintFields): boolean {
  return Boolean(
    record.fingerprint_digest ||
      record.fingerprint_error ||
      record.fingerprint_status === 'queued'
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="text-gray-400">{children}</span>
}

export default function Fingerprint({ record }: { record: FingerprintFields }) {
  if (record.fingerprint_error) {
    return (
      <div className="text-xs text-amber-700">
        approved, but not fingerprinted — {record.fingerprint_error}
      </div>
    )
  }

  const committed = record.fingerprint_correlation_hash
  const queued = record.fingerprint_status === 'queued' && !record.fingerprint_digest

  if (!queued && !record.fingerprint_digest) return null

  return (
    <div className="space-y-0.5 font-mono text-[11px] text-gray-600">
      {committed && (
        <div>
          <Label>committed at approval </Label>
          {committed}
          <Label> (identifies the request, not the document)</Label>
        </div>
      )}

      {queued ? (
        <div className="text-gray-500">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500 align-middle" />
          <Label> queued with ffug — trace </Label>
          {record.fingerprint_trace_id}
        </div>
      ) : (
        <>
          {record.fingerprint_document && (
            <div>
              <Label>document </Label>
              {JSON.stringify(record.fingerprint_document)}
            </div>
          )}
          <div>
            <Label>primed with </Label>
            {record.fingerprint_prime}
            <Label> (this tenant&rsquo;s, from the bus)</Label>
          </div>
          <div>
            <Label>returned sha256 </Label>
            {record.fingerprint_digest}
          </div>
          {committed && (
            // A state, deliberately, and not the two hashes side by side under a
            // heading that implies comparison. What matched is H against Porth's
            // recomputation of H from the callback's VERIFIED claims — a check
            // this screen cannot perform and must not appear to.
            <div className="text-green-700">
              ✓ callback accepted on the committed hash
              {record.fingerprint_trace_id && (
                <Label> — trace {record.fingerprint_trace_id}</Label>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
