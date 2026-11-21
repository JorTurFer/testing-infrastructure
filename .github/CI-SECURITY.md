# CI security model for this repository

This repository manages the cloud infrastructure used by KEDA's end-to-end tests (AWS, GCP and Azure). Its CI can create and delete cloud resources, so it must never run untrusted code with cloud credentials.

## What changed and why
The previous `Validate PR` workflow used `pull_request_target`, checked out the pull request code and ran `terraform plan` with cloud credentials. Terraform can execute code during `plan` (for example `data "external"`), so any pull request could run commands with those credentials. This was exploited in November 2026.

## Model
1. **Static checks (no credentials).** `Validate PR` / `static` runs on every pull request, including forks, with the `pull_request` trigger, no secrets, no OIDC token and read-only permissions. It runs `.github/scripts/terraform-precheck.py` (taken from `main`, never from the pull request) and then `terraform fmt`, `init -backend=false`, `validate` and `tflint`.
2. **Plan (manual approval).** `Validate PR` / `plan` only runs for branches of this repository (never forks) and only after a maintainer approves the `terraform-plan` environment. It re-runs the pre-check on the exact commit being planned and then runs `terraform plan` with a **read-only** identity.
3. **Apply (`main` only).** `Deploy infrastructure` only runs from `main`, in the `terraform-apply` environment (manual approval, deployment branch restricted to `main`), with a separate identity.

## What the pre-check rejects
`data "external"` and any resource or data source of a provider that is not allowed, calls to built-in functions that read files of the runner (`file`, `templatefile`, `filebase64`, `fileset`, ...) because they can print the job environment or credential files into the log, `nonsensitive()` because it can print secrets that live in the state, `provisioner` blocks, providers with a `source` outside the allowed list, modules that are not local paths, changes to the `backend` block, `provider` blocks with attributes that could redirect credentials (`endpoints`, custom endpoints, proxies...), CLI config files and committed `.terraform` directories. The lists live in the script. Changing them requires a change merged into `main`.

## Required GitHub settings (not stored in the repository)
- Environments `terraform-plan` and `terraform-apply` with **required reviewers** (maintainers) and **prevent self-review**. `terraform-apply` restricted to the `main` branch.
- Cloud identifiers and role names as **environment secrets** (not repository secrets): `AZURE_PLAN_CLIENT_ID`, `AZURE_APPLY_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_PLAN_ROLE_TO_ASSUME`, `AWS_APPLY_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PLAN_SERVICE_ACCOUNT`, `GCP_APPLY_SERVICE_ACCOUNT`, `BACKEND_STORAGE_ACCOUNT_NAME`, `BACKEND_STORAGE_CONTAINER_NAME`, `BACKEND_STORAGE_RESOURCE_GROUP_NAME`.
- A GitHub App for the Terraform `github` provider (`TF_APP_ID` variable and `TF_APP_PRIVATE_KEY` secret in `terraform-apply`), limited to the repositories Terraform manages. No personal access tokens.
- Settings > Actions > General: require approval for all outside collaborators; read-only `GITHUB_TOKEN` by default; do not send write tokens to workflows from forks.
- Branch protection on `main` and code owners for `terraform/`, `.github/` and the pre-check.
- The cloud identities must trust the **environment** (`...:environment:terraform-plan` / `terraform-apply`), not "any workflow of this repository", and must not be Owner or AdministratorAccess.

## Bootstrap note
The first pull request that introduces this model cannot pass its own `static` job, because the pre-check script does not exist in `main` yet (the job reads it from `main` on purpose). Merge that first pull request with a maintainer bypass, then every later pull request is checked against the script in `main`.

## Reporting
Please report suspected security problems privately to the maintainers instead of opening a public issue.
