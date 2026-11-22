terraform {
  required_version = ">= 1.10.5"

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "=3.1.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "=3.6.3"
    }
  }
}
