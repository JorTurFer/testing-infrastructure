# TFLint configuration. Plugins are downloaded by `tflint --init` (versions are pinned on purpose).
config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  version = "0.17.0"
  source  = "github.com/terraform-linters/tflint-ruleset-terraform"
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

plugin "azurerm" {
  enabled = true
  version = "0.33.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

plugin "google" {
  enabled = true
  version = "0.41.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}
