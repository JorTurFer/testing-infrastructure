# CI security model for this repository

This repository manages the cloud infrastructure used by KEDA's end-to-end tests (AWS, GCP and Azure). Its CI can create and delete cloud resources, so it must never run untrusted code with powerful cloud credentials.

## What changed and why
The previous `Validate PR` workflow used `pull_request_target`, checked out the pull request code and ran `terraform plan` with cloud credentials. Terraform can execute code during `plan` (for example `data "external"`), so any pull request could run commands with those credentials. This was exploited in November 2026.

## Model
| Workflow / job | Trigger | Code it runs | Environment | Identities |
|---|---|---|---|---|
| `Validate PR` / `static` | `pull_request` (forks too) | the PR | none | none (no secrets, no OIDC) |
| `Validate PR` / `plan` | `pull_request`, same-repo branches only, not Dependabot | the PR, after the pre-check | `terraform-plan` (no reviewers) | read-only |
| `Deploy infrastructure` / `plan` | push to `main`, schedule, manual | `main` | `terraform-plan` | read-only |
| `Deploy infrastructure` / `apply` | after `plan` | `main` | `terraform-apply` (required reviewers, `main` only) | apply (write, least privilege) |
| `Garbage Collector` | schedule, manual | `main` | `e2e-cleanup` | cleanup (list/delete only the GC's services) |

Key ideas:
1. **The only human gate that protects write access is the approval of `terraform-apply`.** The approver reads the plan published in the run summary of the `plan` job first. Nothing in a pull request can reach the apply identities.
2. **PR plans run automatically with read-only identities.** The `terraform-plan` environment has no reviewers so that maintainers are not slowed down; it exists to scope the secrets and the OIDC subject so no other workflow can use them. Forks only get the `static` job.
3. **Every identity is bound to a GitHub environment** (`sub = repo:kedacore/testing-infrastructure:environment:<name>`), never to the whole repository or to a ref (for `pull_request_target` the ref is `main`, so ref-based trust is meaningless). The apply identities should also require `job_workflow_ref` = `main.yaml` on `main`.
4. **Read-only is not "no secrets".** The Terraform state contains secrets (for example service account keys and access keys created for the e2e tests). The plan identities therefore must not be able to read the state storage with a broader scope than needed, and the plan must never be uploaded as an artifact (artifacts of a public repository can be downloaded by anyone with read access).
5. **The GitHub provider uses GitHub Apps, not a personal access token.** One read-only App for plans (`secrets: read`, `metadata: read`) and one for apply (`secrets: write`, limited to the repositories Terraform manages). The private key of an App can mint tokens with all of the App's permissions, which is why there are two.
6. **The e2e service accounts created by Terraform have least-privilege roles** (not `roles/owner`), and the IAM admin used by `apply` can only grant a restricted list of roles. The e2e tests do need static keys for their scalers; the mitigation is limiting what those keys can do.

## What the pre-check rejects
`data "external"` and any resource or data source of a provider that is not allowed, calls to built-in functions that read files of the runner (`file`, `templatefile`, `filebase64`, `fileset`, ...) because they can print the job environment or credential files into the log, `nonsensitive()` because it can print secrets that live in the state, `provisioner` blocks, providers with a `source` outside the allowed list, modules that are not local paths, changes to the `backend` block, `provider` blocks with attributes that could redirect credentials (`endpoints`, custom endpoints, proxies...), CLI config files and committed `.terraform` directories. The lists live in `.github/scripts/terraform-precheck.py`, which every workflow takes from `main`. Changing them requires a change merged into `main`.

## Required GitHub settings (not stored in the repository)
- Environments:
  - `terraform-plan`: no required reviewers.
  - `terraform-apply`: **required reviewers** (maintainers), **prevent self-review**, deployment branches restricted to `main`.
  - `e2e-cleanup`: deployment branches restricted to `main`.
- Cloud identifiers and role names as **environment secrets**, not repository secrets:
  - `terraform-plan`: `AZURE_PLAN_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_PLAN_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PLAN_SERVICE_ACCOUNT`, `BACKEND_STORAGE_ACCOUNT_NAME`, `BACKEND_STORAGE_CONTAINER_NAME`, `BACKEND_STORAGE_RESOURCE_GROUP_NAME`, variable `TF_PLAN_APP_ID`, secret `TF_PLAN_APP_PRIVATE_KEY`.
  - `terraform-apply`: `AZURE_APPLY_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_APPLY_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_APPLY_SERVICE_ACCOUNT`, the three `BACKEND_STORAGE_*` secrets, variable `TF_APP_ID`, secret `TF_APP_PRIVATE_KEY`.
  - `e2e-cleanup`: `AZURE_CLEANUP_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_CLEANUP_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_CLEANUP_SERVICE_ACCOUNT`.
- Settings > Actions > General: require approval for all outside collaborators; read-only `GITHUB_TOKEN` by default; do not send write tokens to workflows from forks.
- Branch protection on `main` and code owners for `terraform/`, `.github/` and the pre-check.
- The cloud identities must trust the **environment**, not "any workflow of this repository", and must not be Owner or AdministratorAccess.

## Residual risks (accepted)
- A maintainer can still approve a malicious apply. The plan in the run summary is what they review; read it, including changes to IAM and to anything that creates credentials.
- A same-repo branch plan runs with read-only identities. Write access to this repository (branch creation) is therefore a trusted capability; keep it limited to maintainers.
- Actions are referenced by version for readability; pin them by SHA (Dependabot/Renovate can keep them updated).

## Bootstrap note
The first pull request that introduces this model cannot pass its own `static` job, because the pre-check script does not exist in `main` yet (the job reads it from `main` on purpose). Merge that first pull request with a maintainer bypass, then every later pull request is checked against the script in `main`. Create the environments, identities and secrets above before merging; keep the old trust cuts in place until the new identities have been tested.

## Reporting
Please report suspected security problems privately to the maintainers instead of opening a public issue.
