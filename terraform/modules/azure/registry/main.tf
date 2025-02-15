provider "azurerm" {
  features {}
}

locals {
  registry_name = "${var.unique_project_name}proxy"
  username      = "e2e-cluster-puller"
}

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

resource "azurerm_container_registry" "acr" {
  name                = local.registry_name
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "Basic"
  tags                = var.tags
}

resource "azurerm_container_registry_scope_map" "acr_policy" {
  name                    = "e2e-cluster-puller"
  container_registry_name = azurerm_container_registry.acr.name
  resource_group_name     = data.azurerm_resource_group.rg.name
  actions = [
    "repositories/*/content/read",
  ]
}

resource "azurerm_container_registry_token" "acr_user" {
  name                    = local.username
  container_registry_name = azurerm_container_registry.acr.name
  resource_group_name     = data.azurerm_resource_group.rg.name
  scope_map_id            = azurerm_container_registry_scope_map.acr_policy.id
}

resource "azurerm_container_registry_token_password" "acr_token" {
  container_registry_token_id = azurerm_container_registry_token.acr_user.id

  password1 {}
}

resource "azurerm_container_registry_cache_rule" "docker-io" {
  name                  = "docker-io"
  container_registry_id = azurerm_container_registry.acr.id
  target_repo           = "*"
  source_repo           = "docker.io/*"
  // This credentialset has been created manually in the portal using kedacoreci credentials
  // https://learn.microsoft.com/en-us/azure/container-registry/container-registry-artifact-cache?pivots=development-environment-azure-portal#create-new-credentials
  credential_set_id = "${azurerm_container_registry.acr.id}/credentialSets/docker-credentials"
}

resource "azurerm_container_registry_task" "acr_purge_task" {
  name                  = "scheduledAcrPurgeTask"
  container_registry_id = azurerm_container_registry.acr.id
  platform {
    os           = "Linux"
    architecture = "amd64"
  }
  encoded_step {
    task_content = <<EOF
version: v1.1.0
steps: 
  - cmd: acr purge --filter '.*:.*' --untagged --ago 15d
    disableWorkingDirectoryOverride: true
    timeout: 3600
EOF
  }
  timer_trigger {
    name     = "t1"
    schedule = "0 0 * * Tue"
    enabled  = true
  }

  tags = var.tags
}