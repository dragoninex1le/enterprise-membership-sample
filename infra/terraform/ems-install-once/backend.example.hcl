# Copy to backend.ems.hcl and edit. Gitignored — it names an account's bucket.
#
#   terraform init -backend-config=backend.ems.hcl
#
# The bucket must already exist; Terraform cannot create the bucket that holds
# its own state. See the README for the bootstrap commands.

bucket = "REPLACE-ems-terraform-state"
key    = "ems-install-once/terraform.tfstate"
region = "us-east-1"
