import { useEffect, useState } from 'react'
import { sampleApiClient } from '../api/sampleApp'
import { usePorthContext } from '../context/PorthContext'

interface DashboardSummary {
  outstanding_invoices: number
  total_ar: number
  bills_due: number
  total_ap: number
  pending_approvals: number
  cash_position: number
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(value)
}

export default function DashboardPage() {
  const { currentUser } = usePorthContext()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!currentUser) return
    setLoading(true)
    setError(null)
    sampleApiClient
      .get<DashboardSummary>('/sample/dashboard')
      .then(r => setSummary(r.data))
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [currentUser])

  const cards: Array<{ label: string; sub: string; value: string }> = summary
    ? [
        { label: 'Outstanding Invoices', sub: 'Accounts Receivable', value: String(summary.outstanding_invoices) },
        { label: 'Total AR', sub: 'Accounts Receivable', value: formatCurrency(summary.total_ar) },
        { label: 'Bills Due', sub: 'Accounts Payable', value: String(summary.bills_due) },
        { label: 'Cash Position', sub: 'Net Balance', value: formatCurrency(summary.cash_position) },
      ]
    : []

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Dashboard</h1>
      <p className="text-sm text-gray-500 mb-6">AR/AP summary — outstanding invoices, bills due, cash position</p>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-white rounded-lg border border-gray-200 p-5 animate-pulse">
                <div className="h-3 bg-gray-200 rounded w-1/2 mb-3" />
                <div className="h-8 bg-gray-200 rounded w-3/4 mb-2" />
                <div className="h-3 bg-gray-200 rounded w-2/3" />
              </div>
            ))
          : cards.map(card => (
              <div key={card.label} className="bg-white rounded-lg border border-gray-200 p-5">
                <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">{card.sub}</p>
                <p className="text-3xl font-bold text-gray-900 mb-1">{card.value}</p>
                <p className="text-sm text-gray-600">{card.label}</p>
              </div>
            ))}
      </div>
    </div>
  )
}
