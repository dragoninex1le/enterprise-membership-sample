terraform {
  # 1.10 is where the S3 backend gained native locking (use_lockfile), so this
  # module needs no DynamoDB lock table. Same floor as Porth's own install-once
  # module, deliberately: an operator moving between the two should not have to
  # think about which Terraform they have.
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state, never local. These keys are created once and destroyed never;
  # losing the state does not lose the keys, but it does lose the knowledge that
  # anything manages them — and re-importing a key you cannot identify is worse
  # than the problem this module solves.
  #
  # PARTIAL configuration on purpose: a backend block cannot interpolate, and
  # the bucket differs per install. Supply the rest at init:
  #
  #   terraform init -backend-config=backend.ems.hcl
  #
  # See backend.example.hcl. The bucket must already exist — Terraform cannot
  # create the bucket that holds its own state.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}
