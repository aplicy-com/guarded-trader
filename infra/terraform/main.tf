locals {
  labels = {
    project = "ai-trading-agent"
    managed = "terraform"
  }
}

resource "hcloud_ssh_key" "deploy" {
  name       = "${var.server_name}-deploy"
  public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
  labels     = local.labels
}

# Static IPv4 that outlives the server, so a rebuild keeps the same address
# (needed for the Kraken API-key IP whitelist later). Not auto-deleted.
resource "hcloud_primary_ip" "ipv4" {
  name        = "${var.server_name}-ipv4"
  type        = "ipv4"
  location    = var.location
  auto_delete = false
  labels      = local.labels
}

# Inbound only. Outbound is unrestricted (apt, Docker Hub, Kraken, Anthropic,
# Telegram, healthchecks.io, Tailscale coordination/DERP).
#
# bootstrap_ssh=true  -> SSH from admin_cidr.
# bootstrap_ssh=false -> one inert "sentinel" rule: ICMP from 192.0.2.1/32
#   (RFC 5737 TEST-NET-1, never routed on the internet), so nothing real is
#   allowed. We do NOT rely on an empty rule set meaning "drop everything":
#   an empty firewall once left public SSH reachable (risk S8). A non-empty
#   inbound rule list is the unambiguous "default-deny" form.
# Tailscale is unaffected: its flows are outbound-initiated (conntrack
# allows the replies) and SSH over the tailnet is also protected by the host
# firewall (scripts/harden-host.sh, cloud-init).
resource "hcloud_firewall" "vps" {
  name   = "${var.server_name}-fw"
  labels = local.labels

  dynamic "rule" {
    for_each = var.bootstrap_ssh ? [1] : []
    content {
      description = "Bootstrap SSH from admin_cidr only. Removed by make vps-lockdown."
      direction   = "in"
      protocol    = "tcp"
      port        = "22"
      source_ips  = [var.admin_cidr]
    }
  }

  dynamic "rule" {
    for_each = var.bootstrap_ssh ? [] : [1]
    content {
      description = "Sentinel: keeps inbound non-empty (default-deny). Allows nothing real."
      direction   = "in"
      protocol    = "icmp"
      source_ips  = ["192.0.2.1/32"]
    }
  }
}

resource "hcloud_server" "vps" {
  name        = var.server_name
  server_type = var.server_type
  image       = var.image
  location    = var.location
  labels      = local.labels

  # Passing an SSH key stops Hetzner e-mailing a root password.
  ssh_keys     = [hcloud_ssh_key.deploy.id]
  firewall_ids = [hcloud_firewall.vps.id]

  public_net {
    ipv4_enabled = true
    ipv4         = hcloud_primary_ip.ipv4.id
    ipv6_enabled = false
  }

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    hostname          = var.server_name
    ssh_public_key    = trimspace(file(pathexpand(var.ssh_public_key_path)))
    tailscale_authkey = var.tailscale_authkey
    bootstrap_ssh     = var.bootstrap_ssh
    admin_cidr        = var.admin_cidr
  })

  lifecycle {
    # user_data / ssh_keys / image changes would otherwise force-replace the
    # server, e.g. a lockdown apply run with a different (or dummy) Tailscale
    # key. Replacement must always be deliberate:
    #   terraform apply -replace=hcloud_server.vps   (see rebuild-vps.md)
    ignore_changes = [user_data, ssh_keys, image]
  }
}
