terraform {
  required_version = ">= 1.10.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "=4.81.0"
    }
    mssql = {
      source  = "betr-io/mssql"
      version = "0.3.1"
    }
    random = {
      source  = "hashicorp/random"
      version = "=3.6.3"
    }
  }
}
