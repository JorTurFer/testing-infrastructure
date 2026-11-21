# CI security model for this repository

This repository manages the cloud infrastructure used by KEDA's end-to-end tests (AWS, GCP and Azure). Its CI can create and delete cloud resources, so it must never run untrusted code with cloud credentials.

## What changed and why
The previous `Validate PR` workflow used `pull_request_target`, checked out the pull request code and ran `terraform plan` with cloud credentials. Terraform can execute code during `plan` (for example `data "external"`), so any pull request could run commands with those credentials. This was exploited in November 2026.

## Model
| Workflow / job | Trigger | Code it runs | Environment | Identities |
|---|---|---|---|---|
| `Validate PR` (all jobs) | `pull_request` (forks too) | the PR | none | none (no secrets, no OIDC, `contents: read`) |
| `Deploy infrastructure` / `plan` | push to `main`, schedule, manual | `main` | `terraform-plan` | read-only |
| `Deploy infrastructure` / `apply` | after `plan` | `main` | `terraform-apply` (required reviewers, `main` only) | apply (write, least privilege) |
| `Garbage Collector` | schedule, manual | `main` | `e2e-cleanup` | cleanup (list/delete only the GC's services) |

Key ideas:
1. **A pull request never gets cloud credentials.** There is deliberately no `terraform plan` on pull requests: a plan needs read access to the state, and the state contains secrets (service account keys and access keys created for the e2e tests). Without a pre-check that nobody can maintain safely, the only safe option is to not run PR code with credentials at all.
2. **The review of the diff and the merge are the gate for the code that runs with credentials.** After the merge, `plan` (read-only) runs from `main` and publishes the plan in the run summary. Then `apply` waits for the approval of the `terraform-apply` environment. The approver reads the plan first.
3. **Every identity is bound to a GitHub environment** (`sub = repo:kedacore/testing-infrastructure:environment:<name>`), never to the whole repository or to a ref. The apply identities should also require `job_workflow_ref` = `main.yaml` on `main`.
4. **No plan file is uploaded as an artifact** (it contains secrets, and artifacts of a public repository can be downloaded by anyone with read access).
5. **The GitHub provider uses GitHub Apps, not a personal access token.** One read-only App for plans (`secrets: read`, `metadata: read`) and one for apply (`secrets: write`, limited to the repositories Terraform manages). The private key of an App can mint tokens with all of the App's permissions, which is why there are two.
6. **The e2e service accounts created by Terraform have least-privilege roles** (not `roles/owner`), and the IAM admin used by `apply` can only grant a restricted list of roles. The e2e tests do need static keys for their scalers; the mitigation is limiting what those keys can do.

## Checks on pull requests (`Validate PR`)
All of them are safe to run on untrusted code because they have no credentials:
- `terraform fmt`, `init -backend=false`, `validate`. `init` uses the provider lock file **from `main`** in read-only mode (`-lockfile=readonly`), so a pull request cannot make the job download and run a different provider. A provider upgrade therefore fails here until a maintainer reviews it and merges it with an override; the job prints a warning when the lock file differs.
- TFLint with the Terraform, AWS, AzureRM and Google rulesets (`terraform/.tflint.hcl`, plugin versions pinned).
- Trivy configuration scan of the Terraform (report-only until the existing findings are triaged; then set `exit-code: "1"`).
- `actionlint` and `zizmor` on the workflows (dangerous triggers, template injection, unpinned actions, excessive permissions).
- `go vet` and `go test` for the garbage collector.
- Dependency review (vulnerable or newly added dependencies).
- Dependabot keeps GitHub Actions, Go modules and Terraform providers up to date.

Ideas to add later, if they become worth it: secret scanning (for example gitleaks), `terraform test` for the modules, a cost estimate on the plan after the merge (Infracost), and a plan shown to reviewers before the merge **only if** it can run without reading the state (for example against an empty state with mock providers).

## Required GitHub settings (not stored in the repository)
- Environments:
  - `terraform-plan`: no required reviewers, deployment branches restricted to `main`.
  - `terraform-apply`: **required reviewers** (maintainers), **prevent self-review**, deployment branches restricted to `main`.
  - `e2e-cleanup`: deployment branches restricted to `main`.
- Cloud identifiers and role names as **environment secrets**, not repository secrets:
  - `terraform-plan`: `AZURE_PLAN_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_PLAN_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PLAN_SERVICE_ACCOUNT`, `BACKEND_STORAGE_ACCOUNT_NAME`, `BACKEND_STORAGE_CONTAINER_NAME`, `BACKEND_STORAGE_RESOURCE_GROUP_NAME`, variable `TF_PLAN_APP_ID`, secret `TF_PLAN_APP_PRIVATE_KEY`.
  - `terraform-apply`: `AZURE_APPLY_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_APPLY_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_APPLY_SERVICE_ACCOUNT`, the three `BACKEND_STORAGE_*` secrets, variable `TF_APP_ID`, secret `TF_APP_PRIVATE_KEY`.
  - `e2e-cleanup`: `AZURE_CLEANUP_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AWS_CLEANUP_ROLE_TO_ASSUME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_CLEANUP_SERVICE_ACCOUNT`.
- Settings > Actions > General: require approval for all outside collaborators; read-only `GITHUB_TOKEN` by default; do not send write tokens to workflows from forks.
- Branch protection on `main` (required review, required `Validate PR` checks) and code owners for `terraform/` and `.github/`.
- The cloud identities must trust the **environment**, not "any workflow of this repository", and must not be Owner or AdministratorAccess.

## Residual risks (accepted)
- Whoever can merge to `main` can run code with the plan identity, and (with the approval of a second maintainer) with the apply identity. Review `terraform/` and `.github/` changes with that in mind, including changes to IAM, providers, `data "external"`-like sources and anything that creates credentials.
- Actions are referenced by version for readability; pin them by SHA (Dependabot can keep them updated).
