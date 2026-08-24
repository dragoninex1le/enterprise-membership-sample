output "service_signing_key_arns" {
  description = <<-EOT
    Map of service_id to its context-signing key ARN.

    These are what go in `/porth/{branch}/signing-keys` as `kid` — the concrete
    ARN, never the alias. Also published one-per-service to SSM, which is how
    the deploy reads them without being threaded a Terraform output.
  EOT
  value       = { for k, v in aws_kms_key.service_signing : k => v.arn }
}

output "signing_keys_document" {
  description = <<-EOT
    The bindings this module's keys contribute to `/porth/{branch}/signing-keys`,
    ready to merge.

    NOT the whole document — Porth publishes its own binding for `porth`, and
    the trust list is the union. Merging is the deploy's job; this output exists
    so the values can be eyeballed before they are seeded, and validated with:

      terraform output -json signing_keys_document > ems-keys.json
      python -m porth_common.internal_plane.signing_trust ems-keys.json
  EOT
  value = {
    contract_version = 1
    keys = [
      for k, v in aws_kms_key.service_signing : {
        kid         = v.arn
        service_id  = k
        description = "EMS ${k}"
      }
    ]
  }
}
