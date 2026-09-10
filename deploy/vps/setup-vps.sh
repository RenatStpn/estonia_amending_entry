#!/usr/bin/env bash
#
# One-time VPS setup for relaying the Estonia Company Finder.
# Run as root on a fresh Ubuntu 22.04 / 24.04 VPS:
#
#     sudo bash setup-vps.sh estonia.example.com
#
# Before running:
#   - Point an A record for estonia.example.com at this VPS's public IP
#     (Caddy needs it resolvable to issue the HTTPS certificate).
#
# After running, this script prints the exact ~/.ssh/authorized_keys line
# to add for the Mac's tunnel key (install-mac.sh on the Mac generates that
# key and prints its public half).

set -euo pipefail

DOMAIN="${1:-}"
TUNNEL_USER="tunnel"
TUNNEL_PORT="5050"

if [[ -z "$DOMAIN" ]]; then
	echo "Usage: sudo bash setup-vps.sh <domain>   e.g. estonia.example.com" >&2
	exit 1
fi
if [[ $EUID -ne 0 ]]; then
	echo "Run this as root (sudo bash setup-vps.sh $DOMAIN)." >&2
	exit 1
fi

echo "==> Installing Caddy"
apt-get update -y
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
	| gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
	> /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
apt-get install -y caddy

echo "==> Writing /etc/caddy/Caddyfile for $DOMAIN"
cat >/etc/caddy/Caddyfile <<EOF
$DOMAIN {
	reverse_proxy 127.0.0.1:$TUNNEL_PORT
	encode gzip
	handle_errors {
		respond "Estonia Company Finder is offline right now (the host machine or its tunnel is down). Try again shortly." 502
	}
}
EOF
systemctl reload caddy || systemctl restart caddy

echo "==> Creating '$TUNNEL_USER' user for the reverse SSH tunnel"
if ! id "$TUNNEL_USER" &>/dev/null; then
	adduser --disabled-password --gecos "" "$TUNNEL_USER"
fi
sudo -u "$TUNNEL_USER" mkdir -p "/home/$TUNNEL_USER/.ssh"
sudo -u "$TUNNEL_USER" touch "/home/$TUNNEL_USER/.ssh/authorized_keys"
chmod 700 "/home/$TUNNEL_USER/.ssh"
chmod 600 "/home/$TUNNEL_USER/.ssh/authorized_keys"

echo "==> Hardening sshd (drop dead tunnels quickly, keep forwarding on)"
SSHD_DROPIN="/etc/ssh/sshd_config.d/estonia-tunnel.conf"
mkdir -p /etc/ssh/sshd_config.d
cat >"$SSHD_DROPIN" <<'EOF'
AllowTcpForwarding yes
ClientAliveInterval 30
ClientAliveCountMax 3
EOF
systemctl restart ssh || systemctl restart sshd

echo "==> Firewall (if ufw is present)"
if command -v ufw &>/dev/null; then
	ufw allow OpenSSH || true
	ufw allow 80/tcp || true
	ufw allow 443/tcp || true
fi

cat <<EOF

============================================================
VPS setup done for: $DOMAIN

Next: add the Mac's tunnel public key to this file on the VPS:
  /home/$TUNNEL_USER/.ssh/authorized_keys

as a single line, restricted to only the reverse tunnel:

  restrict,port-forwarding,permitlisten="127.0.0.1:$TUNNEL_PORT" ssh-ed25519 AAAA...THE_MAC_PUBLIC_KEY... estonia-scraper-tunnel

install-mac.sh on the Mac prints that exact line for you.

Then, on the Mac, run:  deploy/mac/install-mac.sh $DOMAIN <this-vps-host>
============================================================
EOF
