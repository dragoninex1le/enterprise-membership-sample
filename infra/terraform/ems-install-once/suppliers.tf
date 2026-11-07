# ── SupplierLink's key pair, per slot ────────────────────────────────────────
#
# The supplier portal (supplier_portal/ in this repo) trusts assertions signed by
# the supplier network, SupplierLink. SupplierLink is fictional, so EMS stands in
# for it — but keeps the roles separate the way a real network would:
#
#   public key   /ems/{slot}/suppliers/supplierlink/public-key            String
#                read by ems-supplier-portal-{slot}, which VERIFIES only
#   private key  /ems/{slot}/suppliers/supplierlink/simulator-private-key SecureString
#                read only by PorthUatRunnerRole, which plays SupplierLink in
#                supplier-proof.yml
#
# The portal function cannot read the private key, so nothing that serves
# requests can produce an assertion. Against a real network, only the public key
# would exist here.
#
# Rotation: taint tls_private_key.supplierlink["<slot>"] and apply. Assertions live
# five minutes; the portal reads the key once per container.

resource "tls_private_key" "supplierlink" {
  for_each = toset(var.supplier_portal_slots)

  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "aws_ssm_parameter" "supplierlink_public_key" {
  for_each = toset(var.supplier_portal_slots)

  name        = "/ems/${each.key}/suppliers/supplierlink/public-key"
  description = "SupplierLink's assertion-signing public key (P-256 PEM) for ${each.key}."
  type        = "String"
  value       = tls_private_key.supplierlink[each.key].public_key_pem
  tags        = merge(local.common_tags, { Feature = "supplier-portal", Slot = each.key })
}

resource "aws_ssm_parameter" "supplierlink_simulator_private_key" {
  for_each = toset(var.supplier_portal_slots)

  name        = "/ems/${each.key}/suppliers/supplierlink/simulator-private-key"
  description = "SupplierLink simulator's signing key for ${each.key} (supplier-proof.yml only)."
  type        = "SecureString"
  value       = tls_private_key.supplierlink[each.key].private_key_pem_pkcs8
  tags        = merge(local.common_tags, { Feature = "supplier-portal", Slot = each.key })
}
