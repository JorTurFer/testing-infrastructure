provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
}

locals {
  key_vault_name = "${var.unique_project_name}-e2e-key-vault"
}

data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

resource "azurerm_key_vault" "vault" {
  name                        = local.key_vault_name
  location                    = var.location
  resource_group_name         = data.azurerm_resource_group.rg.name
  enabled_for_disk_encryption = false
  tenant_id                   = var.tenant_id
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false
  sku_name                    = "standard"

  tags = var.tags
}

resource "azurerm_key_vault_access_policy" "msi_access_policy" {
  count        = length(var.key_vault_applications)
  key_vault_id = azurerm_key_vault.vault.id
  tenant_id    = var.tenant_id
  object_id    = var.key_vault_applications[count.index].principal_id

  secret_permissions = [
    "Get",
    "Set",
    "List",
    "Delete",
    "Recover"
  ]
}

// Other identities (object ids) that need the same access, for example the e2e identity.
resource "azurerm_key_vault_access_policy" "extra_access_policy" {
  count        = length(var.extra_principal_ids)
  key_vault_id = azurerm_key_vault.vault.id
  tenant_id    = var.tenant_id
  object_id    = var.extra_principal_ids[count.index]

  secret_permissions = [
    "Get",
    "Set",
    "List",
    "Delete",
    "Recover"
  ]
}

// The identities that run Terraform (plan and apply) get their access policy on this vault by hand (az keyvault set-policy with
// get/list/set/delete/recover on secrets for the apply identity, get/list for the plan one). Terraform needs to read the
// secrets below while refreshing, before it could create a policy for the identity that is running it.
resource "azurerm_key_vault_secret" "secrets" {
  count        = length(var.secrets)
  name         = var.secrets[count.index].name
  value        = var.secrets[count.index].value
  key_vault_id = azurerm_key_vault.vault.id
}