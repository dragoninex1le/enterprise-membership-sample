output "signing_key_arns" {
  description = "Map of \"service/direction\" to its signing key ARN."
  value       = { for k, v in aws_kms_key.service_signing : k => v.arn }
}

output "signing_keys_document" {
  description = <<-EOT
    This module's bindings for `/porth/{branch}/signing-keys`, in the schema
    porth-common accepts TODAY.

    NOT the whole document — Porth publishes its own binding for `porth`, and
    the trust list is the union. Merging is the deploy's job.

      terraform output -json signing_keys_document > ems-keys.json
      python -m porth_common.internal_plane.signing_trust ems-keys.json

    Deliberately omits `direction` and `public_key`, and that omission is
    temporary rather than a disagreement with PORTH-623. `SigningKeyBinding` is
    declared `extra="forbid"`, so a document carrying fields the installed
    porth-common does not know is not merely ignored — it fails to load, and a
    trust list that fails to load refuses every internal call on this install.

    The values are ready in `signing_keys_pending_schema` below. Move them into
    this document in the same change that takes the porth-common version which
    understands them.
  EOT
  value = {
    contract_version = 1
    keys = [
      for k, v in aws_kms_key.service_signing : {
        kid         = v.arn
        service_id  = local.signing_keys[k].service_id
        description = "EMS ${local.signing_keys[k].service_id} (${local.signing_keys[k].direction})"
      }
    ]
  }
}

output "signing_keys_pending_schema" {
  description = <<-EOT
    The same bindings with the two fields PORTH-623 adds — `direction` and the
    captured `public_key` — for when porth-common's `SigningKeyBinding` accepts
    them.

    `direction` is what lets a request ingress refuse a response-direction kid
    and vice versa, so a compromised completion path cannot mint a request even
    as its own service. `public_key` is what makes verification local: no
    `kms:Verify` grant anywhere, and no KMS call at verify time that an
    AccessDenied could disguise as `bad_signature`.

    Captured here because `GetPublicKey` is called once, at provisioning, not
    per verification.
  EOT
  value = {
    contract_version = 1
    keys = [
      for k, v in aws_kms_key.service_signing : {
        kid         = v.arn
        service_id  = local.signing_keys[k].service_id
        direction   = local.signing_keys[k].direction
        public_key  = data.aws_kms_public_key.service_signing[k].public_key_pem
        description = "EMS ${local.signing_keys[k].service_id} (${local.signing_keys[k].direction})"
      }
    ]
  }
}
