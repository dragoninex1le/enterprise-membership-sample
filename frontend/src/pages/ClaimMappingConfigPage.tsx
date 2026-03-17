// PORTH-131 — Claim mapping configuration screen
import { useParams } from 'react-router-dom'
export default function ClaimMappingConfigPage() {
  const { tenantId } = useParams()
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Claim Mapping Config</h1>
      <p className="text-gray-400 text-sm">Tenant: {tenantId} &mdash; implementation pending (PORTH-131)</p>
    </div>
  )
}
