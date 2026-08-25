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

variable "signing_keys" {
  description = <<-EOT
    The `(service_id, direction)` pairs that need their own signing CMK.

    **A key set is per direction** (PORTH-623, Richard 2026-08-24). A service's
    request authority and its response authority are different kinds of
    authority, so they are different keys, and a role holds Sign for at most one
    pair. A compromised completion path therefore cannot mint a *request* even
    as its own service — the signature proves which service produced it and
    which kind it is.

    **Provisioned as roles actually need them, never 2N up front.** Today that
    is exactly one:

      ffug / response  — ffug signs only when it completes async work and calls
                         back. It never originates a request.

    Deliberately absent: a request key for the sample app. The app is not a
    service in this model — the existing install key
    (`PorthContextSigningKeyArn`) serves as the request key, so minting one here
    would create a second request authority for the same party.

    `service_id` must match `/porth/{branch}/services` and the trust list; the
    pattern is the one porth-common's `SigningKeyBinding.service_id` enforces.
  EOT
  type = list(object({
    service_id = string
    direction  = string
  }))
  default = [
    { service_id = "ffug", direction = "response" },
  ]

  validation {
    condition = alltrue([
      for k in var.signing_keys : can(regex("^[a-z][a-z0-9-]{0,62}$", k.service_id))
    ])
    error_message = "each service_id must match ^[a-z][a-z0-9-]{0,62}$ — the pattern porth-common's SigningKeyBinding enforces."
  }

  validation {
    condition = alltrue([
      for k in var.signing_keys : contains(["request", "response"], k.direction)
    ])
    error_message = "direction must be 'request' or 'response' — a request ingress accepts only request-direction kids, and a callback ingress only response-direction."
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
