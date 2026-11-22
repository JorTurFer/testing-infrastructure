variable "resource_group_name" {
  type        = string
  description = "Resource group where the roles are assigned"
}

variable "unique_project_name" {
  type        = string
  description = "Value to make unique every resource name generated"
}

variable "roles" {
  type        = set(string)
  description = "Built-in roles assigned to the identity on the resource group"
  default = [
    "Azure Kubernetes Service Cluster User Role",
    "Azure Kubernetes Service Contributor Role",
    "Monitoring Reader",
  ]
}

variable "secret_validity_hours" {
  type        = string
  description = "Validity of the client secret, in hours (Go duration, for example 17520h = 2 years). Rotate it with `terraform taint`."
  default     = "17520h"
}
