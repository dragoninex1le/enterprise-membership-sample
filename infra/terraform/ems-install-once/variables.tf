variable "aws_region" {
  description = <<-EOT
    Region the keys are created in. Must match the region the EMS stack deploys
    to — a key in another region is invisible to the functions that need it, and
    the failure is an AccessDenied on a key ARN that looks perfectly valid.

    Defaulted rather than left to the environment. Porth's own install-once
    module has no provider block and relies on AWS_REGION being exported, which
    works right up until it is not: `terraform validate` passes either way, so
    the first sign is `Error: invalid AWS Region:` — an empty value, at plan
    time, with no indication of where it was supposed to come from.
  EOT
  type        = string
  default     = "us-east-1"
}

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
    # BOTH directions, because ffug is on both legs of the conversation
    # (Richard, 2026-08-25).
    #
    # The response key was here first and the request key was left out on the
    # reasoning that ffug never originates — it answers, and answers are the
    # response direction. That reasoning is sound only while the calling app is
    # a SEPARATE service signing with its own key, which is the shape being
    # corrected: ffug is the service, the sample app is part of it, so the
    # request going in is ffug's too.
    #
    # One direction really is right for a service that only ever answers a
    # caller who is genuinely someone else — fire-and-forget, or a pure callee.
    # That is not this.
    { service_id = "ffug", direction = "request" },
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

variable "deploy_role_name" {
  description = <<-EOT
    The GitHub Actions deploy role for this app's stack — the identity
    CloudFormation acts as, since deploy.yml passes no --role-arn.

    Created by Porth's receiving-account bootstrap template, which is generic:
    it grants what ANY receiving app needs and cannot know what this one
    creates. The grants attached here are the difference, and they are EMS's
    because the resources that need them are.

    Empty to skip, for an install that manages this role by hand.
  EOT
  type        = string
  default     = "sample-app-deploy-role"
}

variable "porth_environment" {
  description = <<-EOT
    The deployment axis — what suffixes function and table names.

    A DIFFERENT value from porth_branch, which selects configuration, and from
    the ADR-Z8 slot in partition keys. Three axes that all read "dev" on this
    install and are not interchangeable; composing a name from the wrong one
    produces something that deploys and is never found.
  EOT
  type        = string
  default     = "dev"
}
