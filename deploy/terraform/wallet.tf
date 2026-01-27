# Panama Papers PoC - Wallet Generation via Terraform

resource "random_password" "wallet_password" {
  length           = 16
  special          = true
  override_special = "#_"
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 1
}

resource "oci_database_autonomous_database_wallet" "panama_wallet" {
  autonomous_database_id = oci_database_autonomous_database.panama_papers_adb.id
  password               = random_password.wallet_password.result
  generate_type          = "SINGLE"
  base64_encode_content  = true
}

resource "local_file" "wallet_zip" {
  content_base64 = oci_database_autonomous_database_wallet.panama_wallet.content
  filename       = "${path.module}/../../.wallet/wallet.zip"
}

resource "local_file" "wallet_password" {
  content  = random_password.wallet_password.result
  filename = "${path.module}/../../.wallet/wallet_password.txt"
}
