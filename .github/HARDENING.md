# CI hardening log

Short record of the CI/cloud hardening done after the November 2026 incident (a pull request ran code with cloud
credentials through `pull_request_target` + `terraform plan`), and why. Update it as items are completed.

## Done (pull request #255)
| Change | Why |
|---|---|
| `Validate PR` runs on `pull_request`, with no secrets, no OIDC and read-only permissions. No `terraform plan` on PRs. | PR code must never run with cloud credentials; a plan needs read access to the state, which contains secrets. |
| Checks on PRs: `fmt`, `validate`, TFLint, Trivy (report-only), actionlint, zizmor, `go vet/test`, dependency review. | Catch problems without credentials. |
| `terraform init` on PRs uses the provider lock file from `main` (`-lockfile=readonly`). | A PR cannot make CI download and run another provider. Provider upgrades need a maintainer override. |
| `Deploy infrastructure` split into `plan` (read-only, `main` only) and `apply` (needs approval of the `terraform-apply` environment). No plan artifact. | Writes need a human gate after reading the plan; artifacts of a public repo are readable by anyone. |
| Cloud identities per purpose (plan, apply, cleanup), each bound to a GitHub **environment**, not to the repo or a ref. | Trust "any workflow of the repo" is what was abused. |
| GitHub Apps (read-only for plan, write for apply) instead of a personal access token. | A PAT lives until revoked and has broad scope. |
| `.terraform.lock.hcl` committed. | Pins provider versions and hashes. |
| GCP e2e service account: specific roles instead of `roles/owner`. | Limit what the static key used by the e2e tests can do. |
| Grafana module and provider removed. | Not used anymore; one less token. |
| Renovate replaces Dependabot (same conventions as the other kedacore repos). | Digest pinning, minimum release age, monthly Terraform provider PR. |
| `cleanup.yaml` runs from `main` only, in the `e2e-cleanup` environment, with its own identities. | It must not share identities with Terraform. |

## Settings outside the repository (checklist)
- [ ] Environments `terraform-plan` (no reviewers), `terraform-apply` (required reviewers, `main` only), `e2e-cleanup` (`main` only).
- [ ] Cloud identifiers as environment secrets (names are in the workflow files); old repository secrets removed.
- [ ] Plan / apply / cleanup identities in AWS, GCP and Azure, trusting the environment (not Owner / AdministratorAccess).
- [ ] Two GitHub Apps (plan: `secrets: read`; apply: `secrets: write` on `keda` and `testing-infrastructure`).
- [ ] Settings > Actions > General: approval for all outside collaborators, read-only `GITHUB_TOKEN` by default, no write tokens for fork workflows.
- [ ] Branch protection on `main` with the `Validate PR` checks required; `CODEOWNERS` owners decided.
- [ ] Renovate app enabled for this repository.
- [ ] `Prevent self-review` on `terraform-apply` once there is a second reviewer.

## Pending
- [ ] Pin every action by SHA (Renovate will open the PR).
- [ ] Trivy: triage the findings, then make it blocking (`exit-code: "1"`).
- [ ] Verify the reduced e2e GCP roles with a real e2e run (extend with `additional_e2e_roles` if needed).
- [ ] Trial the workflows in a test repository (one benign PR, one malicious `main.tf`).
- [ ] Ideas: secret scanning (gitleaks), `terraform test` for modules, cost estimate after the merge.

## Known trade-offs
- Whoever can merge to `main` can run code with the plan identity, and with the apply identity after the approval. Review changes to `terraform/` and `.github/` with that in mind.
- The e2e tests need static keys for their scalers; the mitigation is limiting their roles, not removing them.
