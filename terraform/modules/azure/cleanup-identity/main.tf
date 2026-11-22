// Keyless identity of the Garbage Collector workflow. It only trusts the GitHub environment of this repository.

data "azuread_client_config" "current" {}

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

resource "azuread_application" "cleanup" {
  display_name = "${var.unique_project_name}-e2e-cleanup"
  owners       = [data.azuread_client_config.current.object_id]

  lifecycle {
    ignore_changes = [owners]
  }
}

resource "azuread_service_principal" "cleanup" {
  client_id = azuread_application.cleanup.client_id
  owners    = [data.azuread_client_config.current.object_id]

  lifecycle {
    ignore_changes = [owners]
  }
}

resource "azuread_application_federated_identity_credential" "github" {
  application_id = azuread_application.cleanup.id
  display_name   = "github-environment-${var.github_environment}"
  description    = "GitHub Actions, environment ${var.github_environment} of ${var.github_repository}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:environment:${var.github_environment}"
}

// The garbage collector deletes Cosmos DB accounts, Event Hubs and generic resources of the resource group.
resource "azurerm_role_assignment" "cleanup" {
  scope                = data.azurerm_resource_group.rg.id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.cleanup.object_id
}
