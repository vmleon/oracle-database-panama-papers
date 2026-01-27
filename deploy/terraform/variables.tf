# Panama Papers PoC - Input Variables

variable "compartment_id" {
  description = "OCI Compartment OCID where resources will be created"
  type        = string
}

variable "region" {
  description = "OCI Region"
  type        = string
  default     = "eu-frankfurt-1"
}

variable "adb_display_name" {
  description = "Display name for the Autonomous Database"
  type        = string
  default     = "PanamaPapersPoC"
}

variable "adb_db_name" {
  description = "Database name (alphanumeric, max 14 characters)"
  type        = string
  default     = "PANAMAPOC"

  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9]{0,13}$", var.adb_db_name))
    error_message = "Database name must be alphanumeric, start with letter, max 14 chars."
  }
}

variable "adb_admin_password" {
  description = "ADMIN user password (min 12 chars, must include upper, lower, number)"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.adb_admin_password) >= 12
    error_message = "Password must be at least 12 characters."
  }
}

variable "adb_cpu_count" {
  description = "Number of ECPUs for the Autonomous Database"
  type        = number
  default     = 2

  validation {
    condition     = var.adb_cpu_count >= 2 && var.adb_cpu_count <= 128
    error_message = "CPU count must be between 2 and 128."
  }
}

variable "adb_storage_tb" {
  description = "Storage size in terabytes"
  type        = number
  default     = 1

  validation {
    condition     = var.adb_storage_tb >= 1 && var.adb_storage_tb <= 128
    error_message = "Storage must be between 1 and 128 TB."
  }
}

variable "adb_license_model" {
  description = "License model: LICENSE_INCLUDED or BRING_YOUR_OWN_LICENSE"
  type        = string
  default     = "LICENSE_INCLUDED"
}

variable "adb_workload" {
  description = "Workload type: DW (Data Warehouse) or OLTP (Transaction Processing)"
  type        = string
  default     = "DW"
}

variable "adb_version" {
  description = "Oracle Database version"
  type        = string
  default     = "23ai"
}

variable "whitelisted_ips" {
  description = "List of IP addresses/CIDR blocks allowed to access the database"
  type        = list(string)
  default     = []  # Empty = allow all (use network ACL for production)
}
