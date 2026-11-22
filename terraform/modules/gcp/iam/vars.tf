variable "identity_providers" {
  type        = list(any)
  description = "Collection of OIDCs to create assignements"
}
variable "additional_e2e_roles" {
  type        = list(string)
  description = "Extra project roles for the e2e service account, only if a test needs them (never roles/owner)"
  default     = []
}
