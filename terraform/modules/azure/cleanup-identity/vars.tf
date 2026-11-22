variable "resource_group_name" {
  type        = string
  description = "Resource group where the garbage collector can delete resources"
}

variable "unique_project_name" {
  type        = string
  description = "Value to make unique every resource name generated"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository (owner/name) that can use this identity"
}

variable "github_environment" {
  type        = string
  description = "GitHub environment of that repository that can use this identity"
}
