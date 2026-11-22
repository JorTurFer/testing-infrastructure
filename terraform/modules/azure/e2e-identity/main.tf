terraform {
  required_providers {
    azuread = {
      source = "hashicorp/azuread"
    }
    azurerm = {
      source = "hashicorp/azurerm"
    }
  }
}

// Identity used by the e2e tests: `az login` to reach the clusters and as the credentials of the Azure scalers under test.
// It is NOT the identity that runs Terraform. It has a client secret (the tests need a static credential) and only the roles
// below on the resource group, never Owner.

data "azuread_client_config" "current" {}

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

resource "azuread_application" "e2e" {
  display_name = "${var.unique_project_name}-e2e-tests"
  owners       = [data.azuread_client_config.current.object_id]

  # The owners are managed outside Terraform (the identity that applies this must keep owning the application)
  lifecycle {
    ignore_changes = [owners]
  }
}

resource "azuread_service_principal" "e2e" {
  client_id = azuread_application.e2e.client_id
  owners    = [data.azuread_client_config.current.object_id]

  lifecycle {
    ignore_changes = [owners]
  }
}

resource "azuread_application_password" "e2e" {
  application_id    = azuread_application.e2e.id
  display_name      = "e2e-tests"
  end_date_relative = var.secret_validity_hours
}

resource "azurerm_role_assignment" "roles" {
  for_each             = var.roles
  scope                = data.azurerm_resource_group.rg.id
  role_definition_name = each.value
  principal_id         = azuread_service_principal.e2e.object_id
}
