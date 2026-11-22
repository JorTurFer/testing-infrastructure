# KEDA Testing infrastructure

This repository is used to generated all the infrastructure for e2e tests in kedacore.

Currently, 3 different parts are stored here:

- GitHub Actions runner provision script (`./runners`)
- Terraform for cloud infrastructure (`./terraform`)
- Garbage collector that deletes stale e2e resources (`./garbage-collector`)

The (terraform generated) infrastructure is divided in different modules grouped by cloud provider, which generate as outputs the required secrets that we need to add as secrets in kedacore.

We use this layout:

```
-> modules
    -> azure
        -> .....
    -> github
        -> .....
    -> .....
```

The `root` directory contains the `.tf` files where every module is added and the global variables that every module needs. This part is also responsible of persisting the state in the backend (`azurerm`).

## Prerequisites:

- Terraform >= 1.10.5
- An Azure Storage Account to be [used as backend](https://www.terraform.io/language/settings/backends/azurerm)
- An [authenticated connection with Azure](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs#authenticating-to-azure)
- A [GitHub App](https://registry.terraform.io/providers/integrations/github/latest/docs#authentication) (or token) with the `Secrets` (read and write) and `Metadata` (read) repository permissions.

These prerequisites are only needed to run Terraform by hand. Day to day, Terraform runs in GitHub Actions as described below.

## How changes are made

1. Open a pull request with your change under `terraform/`. **No cloud credentials are available to pull requests**, so there is no `terraform plan` on them. Read the diff carefully: it is what gets reviewed.
2. The `Validate PR` workflow runs on every pull request (forks included) without secrets: `terraform fmt`, `terraform init`/`validate`, TFLint, a Trivy configuration scan, `actionlint` and `zizmor` for the workflows, `go vet` and `go test` for the garbage collector, and a dependency review.
3. Once merged to `main`, the `Deploy infrastructure` workflow runs:
   - `plan` runs from `main` only, with **read-only** cloud identities, and prints the plan in the run summary. Read it.
   - `apply` waits for the approval of a reviewer of the `terraform-apply` environment, then plans again and applies with a different identity that can write. A reviewer should compare its plan with the one from the `plan` job.
   - It also runs every Monday at 07:00 UTC and can be started by hand (`Run workflow`) from `main`.

Nothing else can plan or apply. The apply identity never runs code from a pull request.

### Provider upgrades

Provider versions are pinned in `terraform/terraform.tf` and their hashes in `terraform/.terraform.lock.hcl`. On pull requests `terraform init` uses the lock file **from `main`** in read-only mode, so a pull request that changes a provider fails `Validate PR` until a maintainer has reviewed the change and merges it. Renovate opens one pull request per month with all the Terraform updates.

### Terraform outputs

The modules generate the credentials and settings that the e2e tests need (cloud keys, connection strings, role ARNs...) and write them as secrets of the `kedacore/keda` repository through the `github` provider. Every apply that recreates a key updates those secrets.

The GCP service account used by the e2e tests only has the roles listed in `terraform/modules/gcp/iam` (`additional_e2e_roles` adds more). If an e2e test needs another role, add it there **and** to the list of roles that the apply identity may grant (see below).

## GitHub environments and identities

Cloud access is keyless (OIDC), and every identity trusts one GitHub **environment** of this repository, never "any workflow of the repository":

| Environment | Used by | Cloud identities | Approval |
|---|---|---|---|
| `terraform-plan` | `Deploy infrastructure` / `plan` | read-only (`tf-plan`, `keda-tf-plan`) | none, `main` only |
| `terraform-apply` | `Deploy infrastructure` / `apply` | write, limited to what the modules manage (`tf-apply`, `keda-tf-apply`, `github-testing-infra`) | required reviewers, `main` only |
| `e2e-cleanup` | `Garbage Collector` | list and delete the resources the garbage collector cleans | none, `main` only |

Per-environment secrets (identity, role or service account of each cloud, and the private key of the GitHub App of that environment) and the shared ones (tenant, subscription, workload identity provider, state storage) are listed in `.github/workflows/main.yaml` and `.github/workflows/cleanup.yaml`. The Client ID of each GitHub App is the **variable** `TF_PLAN_APP_CLIENT_ID` / `TF_APP_CLIENT_ID`.

What is not managed by Terraform, because it is what Terraform runs with:

- The `tf-plan` / `tf-apply` roles and policies in AWS, the `keda-tf-plan` / `keda-tf-apply` app registrations in Azure (with the custom role `keda-tf-plan-refresh`) and the `tf-plan` / `github-testing-infra` service accounts, the workload identity provider and their IAM bindings in GCP.
- The apply identity in GCP can only grant the roles of the e2e service account (an IAM condition on `roles/resourcemanager.projectIamAdmin`); in Azure it can only assign the roles that the modules use; in AWS it can only manage the IAM names that the module creates (`keda-*`, `e2e-test-*`).
- The GitHub Apps, the environments and their protection rules.

If a module needs a new kind of resource or permission, the plan or the apply fails with an authorization error that names the missing action: extend the matching identity by hand and run the workflow again.

## Garbage collector

`Garbage Collector` runs every 12 hours from `main` and deletes stale e2e resources (GCP Spanner instances, AWS Managed Prometheus, DynamoDB, Kinesis and SQS, Azure Cosmos DB, Event Hubs and resources). It can be started by hand and `go run . --dry-run=true` in `garbage-collector` lists what it would delete.

## Dependencies

Renovate keeps GitHub Actions (pinned by digest), Go modules, Docker images and Terraform providers up to date. Updates wait three days after their release before a pull request is opened.
