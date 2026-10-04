# --- Secrets: env vars only (TF_VAR_*), never a tfvars file ---------------

variable "hcloud_token" {
  description = "Hetzner Cloud API token (Read & Write). Supply via TF_VAR_hcloud_token."
  type        = string
  sensitive   = true
}

variable "tailscale_authkey" {
  description = "Tailscale auth key used once by cloud-init to join the tailnet. Supply via TF_VAR_tailscale_authkey. Must be single-use (non-reusable) with a short expiry."
  type        = string
  sensitive   = true

  validation {
    condition     = startswith(var.tailscale_authkey, "tskey-")
    error_message = "tailscale_authkey must be a Tailscale auth key (starts with \"tskey-\")."
  }
}

# --- Non-secret settings (see terraform.tfvars.example) -------------------

variable "admin_cidr" {
  description = "CIDR allowed to reach SSH (22) during bootstrap, e.g. your public IP as x.x.x.x/32. Ignored once bootstrap_ssh=false."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a valid IPv4 CIDR and must not be 0.0.0.0/0."
  }
}

variable "bootstrap_ssh" {
  description = "true = firewall allows SSH from admin_cidr (first provision only). false = no inbound rules at all (steady state; access is over Tailscale)."
  type        = bool
  default     = false
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key authorised for the deploy user."
  type        = string
  default     = "~/.ssh/ai_trader_vps.pub"
}

variable "server_name" {
  description = "Hetzner server name. Also the Tailscale hostname."
  type        = string
  default     = "ai-trader-vps"
}

variable "server_type" {
  description = "Hetzner server type. cx23 = 2 vCPU / 4 GB / 40 GB, the successor to cx22 (cx22 has been unavailable for new orders since 2026-01-01, see ADR-0011)."
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Hetzner location. The CX line is EU-only (nbg1, fsn1, hel1)."
  type        = string
  default     = "nbg1"
}

variable "image" {
  description = "OS image."
  type        = string
  default     = "ubuntu-24.04"
}
