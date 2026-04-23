import { useEffect, useState } from 'react'
import { sampleApiClient } from '../api/sampleApp'
import { usePorthContext } from '../context/PorthContext'
import { PERMISSIONS } from '../constants'

interface Approval {
  record_id: string
  type: string
  amount: string
  submitted_by: string
  submitted_at: string
  status: string
}

const STATUS_BADGE: Record<string, string> = {
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

export default function ApprovalsPage() {
  const { currentUser } = usePorthContext()
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const canWrite = currentUser?.permissions?.includes(PERMISSIONS.APPROVALS_WRITE) ?? false

  useEffect(() => {
    if (!currentUser) return
    setLoading(true)
    setError(null)
    sampleApiClient
      .get<Approval[]>('/sample/approvals')
      .then(r => setApprovals(r.data))
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [currentUser])

  function handleAction(recordId: string, action: 'approve' | 'reject') {
    sampleApiClient
      .post<Approval>(`/sample/approvals/${recordId}/${action}`)
      .then(r => {
        setApprovals(prev =>
          prev.map(a =>
            a.record_id === recordId
              ? { ...a, status: r.data.status ?? (action === 'approve' ? 'approved' : 'rejected') }
              : a
          )
        )
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Approvals</h1>
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
                  'Record ID', 'Type', 'Amount', 'Submitted By', 'Date', 'Status',
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
                <tr key={appr.record_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-mono text-gray-500">{appr.record_id.slice(0, 8)}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 capitalize">{appr.type}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">£{parseFloat(appr.amount).toFixed(2)}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{appr.submitted_by}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {appr.submitted_at ? new Date(appr.submitted_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={appr.status} /></td>
                  {canWrite && (
                    <td className="px-4 py-3">
                      {appr.status === 'pending' && (
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleAction(appr.record_id, 'approve')}
                            className="rounded px-2.5 py-1 text-xs font-medium bg-green-100 text-green-800 hover:bg-green-200"
                          >
                            Approve
                          </button>
                          <button
                            onClick={() => handleAction(appr.record_id, 'reject')}
                            className="rounded px-2.5 py-1 text-xs font-medium bg-red-100 text-red-800 hover:bg-red-200"
                          >
                            Reject
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
