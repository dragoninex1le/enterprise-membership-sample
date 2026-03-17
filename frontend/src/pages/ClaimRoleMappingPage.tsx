// PORTH-132 — Claim-to-role mapping screen and JWT test evaluator
import { useParams } from 'react-router-dom'
export default function ClaimRoleMappingPage() {
  const { tenantId } = useParams()
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Claim-to-Role Mappings</h1>
      <p className="text-gray-400 text-sm">Tenant: {tenantId} &mdash; implementation pending (PORTH-132)</p>
    </div>
  )
}
