output "server_name" {
  description = "Server name (also the Tailscale hostname)."
  value       = hcloud_server.vps.name
}

output "ipv4" {
  description = "Static public IPv4. Used for bootstrap SSH and the Kraken key whitelist."
  value       = hcloud_primary_ip.ipv4.ip_address
}

output "bootstrap_ssh_open" {
  description = "Whether the firewall currently allows public SSH."
  value       = var.bootstrap_ssh
}
