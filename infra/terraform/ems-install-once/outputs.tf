output "signing_key_arns" {
  description = <<-EOT
    Map of "service/direction" to its signing key ARN.

    Also published one-per-pair to SSM, which is how the deploy reads a key
    without being threaded a Terraform output.

    NOT the trust document, and the distinction is the one most likely to be
    misread when looking at Parameter Store. Two families live under
    /porth/{branch}, and only the first is Porth's contract:

      signing-keys/{service_id}            ONE document per service. Its `keys`
                                           list carries every key that service
                                           may sign with, tagged by direction.
                                           This is what verification reads.

      infra/signing-key-arn/{svc}/{dir}    A bare ARN, one per pair. EMS
                                           plumbing, read only by deploy.yml so
                                           the template can name a Resource in
                                           an IAM policy. A KMS key has no
                                           deterministic id, and an alias ARN
                                           cannot be the Resource of a key-
                                           operation policy, so the concrete ARN
                                           has to be published somewhere.

    A service's document listing ONE direction is normal, not a half-finished
    install: ffug only ever answers, so it holds a response key and no request
    key. That absence is the property PORTH-623 exists to create.

    This module DOES write the trust documents (`aws_ssm_parameter.signing_keys`).
    It once did not — registration was `porth-install signing-key register` — and
    PORTH-625 moved it here: with one document per service there is nothing to
    merge with, and the CLI's key-spec check cannot fail for a key this module
    created to that spec. Validating through the runtime's own loader was the one
    part worth keeping, and it moved to a CI test, which runs earlier.
  EOT
  value       = { for k, v in aws_kms_key.service_signing : k => v.arn }
}
