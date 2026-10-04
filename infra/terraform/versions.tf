terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "= 1.69.0"
    }
  }
}

# Token comes from TF_VAR_hcloud_token only (see variables.tf). It is never
# written to a file in this repo.
provider "hcloud" {
  token = var.hcloud_token
}
