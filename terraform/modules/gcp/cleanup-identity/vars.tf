variable "account_id" {
  type        = string
  description = "Account id of the service account"
  default     = "e2e-cleanup"
}

variable "workload_identity_pool" {
  type        = string
  description = "Id of the workload identity pool that trusts GitHub"
}

variable "github_environment" {
  type        = string
  description = "GitHub environment that can impersonate the service account"
}
