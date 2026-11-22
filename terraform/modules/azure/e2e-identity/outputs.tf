output "client_id" {
  value = azuread_application.e2e.client_id
}

output "object_id" {
  description = "Object id of the service principal"
  value       = azuread_service_principal.e2e.object_id
}

output "client_secret" {
  value     = azuread_application_password.e2e.value
  sensitive = true
}
