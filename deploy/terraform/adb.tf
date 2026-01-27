# Panama Papers PoC - Autonomous Database Resource

resource "oci_database_autonomous_database" "panama_papers_adb" {
  compartment_id = var.compartment_id

  # Database identification
  display_name = var.adb_display_name
  db_name      = var.adb_db_name

  # Compute and storage
  compute_model            = "ECPU"
  compute_count            = var.adb_cpu_count
  data_storage_size_in_tbs = var.adb_storage_tb

  # Database configuration
  db_version     = var.adb_version
  db_workload    = var.adb_workload
  license_model  = var.adb_license_model
  admin_password = var.adb_admin_password

  # Network configuration
  is_mtls_connection_required = true # Require wallet for connections

  # Access control (optional - for production, restrict IPs)
  whitelisted_ips = length(var.whitelisted_ips) > 0 ? var.whitelisted_ips : null

  # Features
  is_auto_scaling_enabled             = false
  is_auto_scaling_for_storage_enabled = false

  # Character set for international data
  character_set  = "AL32UTF8"
  ncharacter_set = "AL16UTF16"

  # Free tier eligible (for development)
  is_free_tier = false

  lifecycle {
    # Prevent accidental deletion
    prevent_destroy = false
  }
}
