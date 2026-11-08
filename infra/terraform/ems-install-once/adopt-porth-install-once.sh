#!/usr/bin/env bash
# Once per install: move Porth's install-once resources out of their own state
# (applied from a Components checkout) into this module's state, under
# module.porth_install_once (porth.tf). Run from this directory after
#
#   terraform init -backend-config=backend.ems.hcl
#
# with credentials that can read and write both state objects.
#
# Dry run first, always: both states are copied to a private temp directory, the
# move is made there, and a plan is taken against the result. Nothing remote is
# touched unless that plan destroys nothing and creates only what this change
# adds (the mint callers' invoke permissions and the deploy role's read of the
# mint key policy). Then the moved state is pushed and the old state object is
# renamed *.retired-<timestamp>, so nobody applies the Components root module
# against it again and takes the callers away.
#
# Never prints state: it holds the SupplierLink simulator's private key.
#
#   ./adopt-porth-install-once.sh            # dry run, then asks before writing
#   OLD_KEY=porth-install-once/dev/terraform.tfstate ./adopt-porth-install-once.sh
set -euo pipefail
cd "$(dirname "$0")"

OLD_BUCKET="${OLD_BUCKET:-porth-tfstate-195950944420}"
OLD_KEY="${OLD_KEY:-porth-install-once/dev/terraform.tfstate}"
ALLOWED_CREATES='^(module\.porth_install_once\.aws_lambda_permission\.delegated_mint_callers\[.*\]|aws_iam_role_policy\.deploy_role_mint_caller_check\[0\])$'

say() { printf '%s\n' "$*" >&2; }
die() { say "STOP: $*"; exit 1; }

[ -d .terraform ] || die "run 'terraform init -backend-config=backend.ems.hcl' here first"
command -v jq >/dev/null || die "jq is required"

if terraform state list | grep -q '^module\.porth_install_once\.'; then
  say "Already adopted: this state holds module.porth_install_once. Nothing to do."
  exit 0
fi

umask 077
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say "1/5 Copying both states into a private temp directory"
aws s3 cp --only-show-errors "s3://${OLD_BUCKET}/${OLD_KEY}" "$WORK/porth.tfstate" \
  || die "cannot read s3://${OLD_BUCKET}/${OLD_KEY}"
terraform state pull > "$WORK/ems.tfstate"
cp "$WORK/ems.tfstate" "$WORK/ems.before.tfstate"

say "2/5 Moving Porth's resources under module.porth_install_once (locally)"
# A separate, backend-less directory, so -state/-state-out can only ever mean
# the local copies — never this directory's remote state.
mkdir "$WORK/mv"
ADDRS="$(cd "$WORK/mv" && terraform state list -state="$WORK/porth.tfstate" | grep -v '^data\.' || true)"
[ -n "$ADDRS" ] || die "the old state holds no resources — wrong OLD_KEY?"
COUNT=0
while IFS= read -r addr; do
  (cd "$WORK/mv" && terraform state mv -lock=false \
     -state="$WORK/porth.tfstate" -state-out="$WORK/ems.tfstate" \
     "$addr" "module.porth_install_once.$addr" >/dev/null)
  COUNT=$((COUNT + 1))
done <<< "$ADDRS"
say "    moved $COUNT resource instances"

say "3/5 Planning this configuration against the moved state (dry run)"
mkdir "$WORK/plan"
cp ./*.tf "$WORK/plan/"
cp .terraform.lock.hcl "$WORK/plan/" 2>/dev/null || true
cat > "$WORK/plan/backend_override.tf" <<EOF
terraform {
  backend "local" {
    path = "$WORK/ems.tfstate"
  }
}
EOF
(cd "$WORK/plan" && terraform init -input=false -reconfigure >/dev/null \
  && terraform plan -input=false -lock=false -out="$WORK/plan.bin" >/dev/null \
  && terraform show -json "$WORK/plan.bin" > "$WORK/plan.json") \
  || die "the dry-run plan failed; nothing remote was changed"

# One line per change: actions, address, and for an update the attributes it
# changes, so a re-tag or a policy edit is visible rather than just "update".
jq -r '.resource_changes[] | select(.change.actions != ["no-op"] and .change.actions != ["read"])
       | .change as $c
       | "\($c.actions | join("+"))\t\(.address)\t\(
           if $c.actions == ["update"] then
             [ (($c.after // {}) + ($c.after_unknown // {})) | keys[]
               | select(($c.before // {})[.] != ($c.after // {})[.]) ] | join(",")
           else "" end)"' "$WORK/plan.json" > "$WORK/changes.tsv"
say "    the plan after adoption (action, address, attributes an update changes):"
if [ -s "$WORK/changes.tsv" ]; then column -t -s $'\t' "$WORK/changes.tsv" | sed 's/^/      /' >&2; else say "      no changes"; fi

# Porth's mint service document is what callers resolve the mint through, so a
# rewrite of it is shown in full, live against planned. That one parameter only,
# by address: it holds a name, an address and a PUBLIC key. (The AWS provider
# marks every parameter's value sensitive, so sensitivity cannot pick it out.)
jq -c '.resource_changes[]
  | select(.change.actions == ["update"]
           and .address == "module.porth_install_once.aws_ssm_parameter.delegated_mint_service_document"
           and .change.before.type == "String"
           and .change.before.value != .change.after.value)
  | {address, live: .change.before.value, planned: .change.after.value}' "$WORK/plan.json" |
while IFS= read -r doc; do
  say "    $(jq -r .address <<<"$doc") — live (<) against planned (>):"
  diff <(jq -r .live <<<"$doc" | jq -S . 2>/dev/null || jq -r .live <<<"$doc") \
       <(jq -r .planned <<<"$doc" | jq -S . 2>/dev/null || jq -r .planned <<<"$doc") \
    | sed 's/^/      /' >&2 || true
done

BAD="$(jq -r --arg ok "$ALLOWED_CREATES" '.resource_changes[]
  | select((.change.actions | index("delete"))
           or ((.change.actions | index("create")) and (.address | test($ok) | not)))
  | "\(.change.actions | join("+"))  \(.address)"' "$WORK/plan.json")"
[ -z "$BAD" ] || die "the plan would destroy or create what it must not:
$BAD
Nothing remote was changed."

say "4/5 Ready to write: push the moved state to this module's backend, and"
say "    rename s3://${OLD_BUCKET}/${OLD_KEY} to *.retired-<timestamp>."
read -r -p "Type 'adopt' to continue: " answer
[ "$answer" = "adopt" ] || die "not confirmed; nothing remote was changed"

terraform state push "$WORK/ems.tfstate"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
aws s3 mv --only-show-errors "s3://${OLD_BUCKET}/${OLD_KEY}" "s3://${OLD_BUCKET}/${OLD_KEY}.retired-${STAMP}"

say "5/5 Done. Now:  terraform plan   — expect only the changes listed above —  then  terraform apply"
say "    Never apply Components' porth-install-once root module with ems.tfvars again:"
say "    its state is retired, and an apply from there would recreate Porth's resources."
