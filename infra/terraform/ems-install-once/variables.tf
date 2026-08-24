variable "porth_branch" {
  description = <<-EOT
    The Porth install's DEPLOYMENT axis — its stack's `Environment` parameter,
    and the segment in every `/porth/{branch}/…` document path. On EMS this is
    `dev`.

    Deliberately NOT the ADR-Z8 data slot (`PorthEnvSlot`, which is `prod` here).
    They are two axes wearing one word and they hold different values on this
    install; the SSM paths this module writes are on the configuration axis.
  EOT
  type        = string
  default     = "dev"
}

variable "service_signing_keys" {
  description = <<-EOT
    EMS services that MINT context envelopes, each of which gets its own
    asymmetric signing CMK (PORTH-623).

    Defaulted here, and that is the difference from Porth's install-once module:
    that one defaults to empty because Porth does not know which services an
    install runs. This module IS the install, so naming its own services is
    exactly right.

    Why one key per service rather than the shared install key: on a single key
    `kms:Sign` is not "permission to sign as yourself" — it is permission to
    mint context for any tenant, as any service, to any audience. The callback
    pattern makes completion functions minters, so on a shared key the class of
    verify-only receivers erodes one service at a time, each addition
    individually reasonable, until there are none left. UAT-4 witnesses that
    class.

    Values must match the `service_id` in `/porth/{branch}/services` and in the
    `/porth/{branch}/signing-keys` trust list — that binding is what makes a
    forged source cryptographically detectable rather than merely unregistered.
    The pattern is the one porth-common's `SigningKeyBinding.service_id`
    enforces; a value accepted here and rejected there would be a key nobody
    could ever use.
  EOT
  type        = list(string)
  default     = ["ffug", "sample-app"]

  validation {
    condition = alltrue([
      for s in var.service_signing_keys : can(regex("^[a-z][a-z0-9-]{0,62}$", s))
    ])
    error_message = "each service_id must match ^[a-z][a-z0-9-]{0,62}$ — the pattern porth-common's SigningKeyBinding enforces."
  }
}

variable "kms_deletion_window_days" {
  description = "Waiting period before a scheduled key deletion completes. 30 is the AWS maximum and the safe default for a key that signs identity."
  type        = number
  default     = 30

  validation {
    condition     = var.kms_deletion_window_days >= 7 && var.kms_deletion_window_days <= 30
    error_message = "kms_deletion_window_days must be between 7 and 30."
  }
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}
