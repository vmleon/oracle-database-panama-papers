# Panama Papers PoC - Terraform Outputs

output "adb_id" {
  description = "Autonomous Database OCID"
  value       = oci_database_autonomous_database.panama_papers_adb.id
}

output "adb_db_name" {
  description = "Database name"
  value       = oci_database_autonomous_database.panama_papers_adb.db_name
}

output "adb_state" {
  description = "Database state"
  value       = oci_database_autonomous_database.panama_papers_adb.state
}

output "service_console_url" {
  description = "Service Console URL"
  value       = oci_database_autonomous_database.panama_papers_adb.service_console_url
}

output "connection_strings" {
  description = "Database connection strings"
  value       = oci_database_autonomous_database.panama_papers_adb.connection_strings
  sensitive   = true
}

output "service_names" {
  description = "TNS service names for wallet connections"
  value = {
    low    = "${lower(oci_database_autonomous_database.panama_papers_adb.db_name)}_low"
    medium = "${lower(oci_database_autonomous_database.panama_papers_adb.db_name)}_medium"
    high   = "${lower(oci_database_autonomous_database.panama_papers_adb.db_name)}_high"
  }
}

output "wallet_password" {
  description = "Wallet password"
  value       = random_password.wallet_password.result
  sensitive   = true
}
