export default function DashboardPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Dashboard</h1>
      <p className="text-sm text-gray-500 mb-6">AR/AP summary — outstanding invoices, bills due, cash position</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: 'Outstanding invoices', value: '—', sub: 'Accounts Receivable' },
          { label: 'Bills due', value: '—', sub: 'Accounts Payable' },
          { label: 'Cash position', value: '—', sub: 'Net balance' },
        ].map(card => (
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
