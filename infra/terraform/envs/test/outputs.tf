output "apim_base_url" {
  value = module.apim.gateway_url
}

output "api_host_url" {
  value = module.app_host.host_url
}

output "functions_name" {
  value = module.functions_host.function_app_name
}

output "sql_server_fqdn" {
  value = module.sql.server_fqdn
}

output "sql_db_name" {
  value = module.sql.database_name
}

output "service_bus_namespace" {
  value = module.service_bus.namespace_fqdn
}

output "api_principal_id" {
  value = module.identities.api_principal_id
}

output "functions_principal_id" {
  value = module.identities.functions_principal_id
}

output "application_insights_connection_string" {
  value     = module.application_insights.connection_string
  sensitive = true
}

output "key_vault_uri" {
  value = module.key_vault.vault_uri
}
