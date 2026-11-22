variable "azure_resource_group_name" {
  default     = "keda-e2e-infrastructure"
  type        = string
  description = "Resource group name where azure resources will be placed"
}

variable "unique_project_name" {
  default     = "keda"
  type        = string
  description = "Value to make unique every resource name generated"
}

variable "repository" {
  default     = "kedacore/keda"
  type        = string
  description = "Repository where secrets will be created/updated"
}

variable "infrastructure_repository" {
  default     = "kedacore/testing-infrastructure"
  type        = string
  description = "This repository, whose GitHub environments use the identities created here"
}

variable "cleanup_environment" {
  default     = "e2e-cleanup"
  type        = string
  description = "GitHub environment of the garbage collector workflow"
}

variable "gcp_github_workload_identity_pool" {
  default     = "github-workload-federation"
  type        = string
  description = "GCP workload identity pool that trusts GitHub Actions (created by hand, not managed by Terraform)"
}

variable "sql_admin_object_id" {
  type        = string
  description = "Object id of the identity that administers the SQL server (the Terraform apply identity). Set with TF_VAR_sql_admin_object_id so every run uses the same value"

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.sql_admin_object_id))
    error_message = "sql_admin_object_id must be an object id (GUID)."
  }
}
