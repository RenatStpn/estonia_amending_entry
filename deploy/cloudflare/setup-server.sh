#!/usr/bin/env bash
#
# One-time setup of the Estonia Company Finder on a fresh Ubuntu 22.04/24.04
# VM (e.g. Oracle Cloud Always Free), exposed to the internet only through a
# Cloudflare Tunnel (outbound connection, so no inbound ports to open).
#
#   sudo bash setup-server.sh
#
# Then, in the Cloudflare dashboard, create the tunnel and run the one
# `cloudflared service install <TOKEN>` command it shows you (see README).

set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash setup-server.sh" >&2; exit 1; }

APP_USER="finder"
APP_DIR="/opt/estonia_amending_entry"
REPO="https://github.com/RenatStpn/estonia_amending_entry.git"

echo "==> Packages"
apt-get update -y
apt-get install -y git python3 python3-venv python3-pip curl

echo "==> App user + code"
id "$APP_USER" &>/dev/null || adduser --system --group --home "$APP_DIR" "$APP_USER"
if [[ -d "$APP_DIR/.git" ]]; then
	git -C "$APP_DIR" pull --ff-only
else
	rm -rf "$APP_DIR"
	git clone "$REPO" "$APP_DIR"
fi
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" gunicorn
mkdir -p "$APP_DIR/data" "$APP_DIR/output"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> systemd service (single worker: searches/results live in memory)"
SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
[[ -f /etc/estonia-finder.env ]] || cat >/etc/estonia-finder.env <<ENV
# Leave APP_PASSWORD empty for an open app, or set one to require a login.
APP_PASSWORD=
APP_USERNAME=team
APP_SECRET_KEY=$SECRET
ENV
chmod 600 /etc/estonia-finder.env
cp "$APP_DIR/deploy/cloudflare/estonia-finder.service" /etc/systemd/system/estonia-finder.service
systemctl daemon-reload
systemctl enable --now estonia-finder
sleep 3
curl -fsS http://127.0.0.1:5050/healthz && echo " <- app is up on 127.0.0.1:5050"

echo "==> cloudflared"
mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
	>/etc/apt/sources.list.d/cloudflared.list
apt-get update -y
apt-get install -y cloudflared

cat <<'DONE'

============================================================
App is running locally on the VM (127.0.0.1:5050).
Next: create the tunnel in the Cloudflare dashboard and run the
`sudo cloudflared service install <TOKEN>` command it gives you.
Point the tunnel's public hostname at:  http://localhost:5050
============================================================
DONE
