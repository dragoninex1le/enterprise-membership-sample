output "signing_key_arns" {
  description = <<-EOT
    Map of "service/direction" to its signing key ARN.

    Also published one-per-pair to SSM, which is how the deploy reads a key
    without being threaded a Terraform output.

    This module deliberately emits **no trust document**. Registration is
    `porth-install signing-key register`, which resolves the ARN, refuses a key
    that is not SIGN_VERIFY/ECC_NIST_P256, captures the public half with
    `kms:GetPublicKey`, merges into whatever is already at
    `/porth/{branch}/signing-keys/{service}`, and validates the result through
    the same code the runtime loads it with. Rebuilding any of that here would
    be a second implementation of a contract that already has one.
  EOT
  value       = { for k, v in aws_kms_key.service_signing : k => v.arn }
}
