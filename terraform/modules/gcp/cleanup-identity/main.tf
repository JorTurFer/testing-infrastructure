data "google_project" "project" {}

// Keyless identity of the Garbage Collector workflow: no service account key exists, GitHub exchanges its OIDC token for access
// to it, and only for jobs of the GitHub environment (the provider of the pool also restricts the repository).

resource "google_service_account" "cleanup" {
  account_id   = var.account_id
  display_name = "KEDA e2e garbage collector"
}

resource "google_project_iam_member" "spanner" {
  project = data.google_project.project.project_id
  role    = "roles/spanner.admin"
  member  = "serviceAccount:${google_service_account.cleanup.email}"
}

resource "google_service_account_iam_member" "github" {
  service_account_id = google_service_account.cleanup.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.project.number}/locations/global/workloadIdentityPools/${var.workload_identity_pool}/attribute.environment/${var.github_environment}"
}
