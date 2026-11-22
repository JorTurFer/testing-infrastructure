variable "github_repository" {
  type        = string
  description = "GitHub repository (owner/name) that can assume the role"
}

variable "github_environment" {
  type        = string
  description = "GitHub environment of that repository that can assume the role"
}

variable "tags" {
  type        = map(string)
  description = "Tags added to the resources"
  default     = {}
}
