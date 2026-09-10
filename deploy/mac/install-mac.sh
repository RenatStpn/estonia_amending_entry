#!/usr/bin/env bash
#
# Sets up the Mac side of the team deployment:
#   - a dedicated SSH key for the reverse tunnel
#   - two launchd agents that keep running and restart on crash/reboot:
#       ee.estonia-scraper.app     -> the Flask app on 127.0.0.1:5050
#       ee.estonia-scraper.tunnel  -> autossh reverse tunnel to the VPS
#
# Usage:
#   deploy/mac/install-mac.sh <domain> <vps-host>
#   e.g. deploy/mac/install-mac.sh estonia.example.com 203.0.113.10
#
# Run deploy/vps/setup-vps.sh on the VPS first. This script pauses and
# prints the authorized_keys line to paste on the VPS before it loads
# the tunnel.

set -euo pipefail

DOMAIN="${1:-}"
VPS_HOST="${2:-}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KEY="$HOME/.ssh/estonia_scraper_tunnel"
LA="$HOME/Library/LaunchAgents"
AUTOSSH="$(command -v autossh || true)"

if [[ -z "$DOMAIN" || -z "$VPS_HOST" ]]; then
	echo "Usage: $0 <domain> <vps-host>" >&2
	exit 1
fi
if [[ -z "$AUTOSSH" ]]; then
	echo "autossh not found. Install it:  brew install autossh" >&2
	exit 1
fi
if [[ ! -x "$PROJECT_DIR/venv/bin/python" ]]; then
	echo "No venv at $PROJECT_DIR/venv. Create it and install requirements first:" >&2
	echo "  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt" >&2
	exit 1
fi

mkdir -p "$LA" "$PROJECT_DIR/logs"

# --- SSH key for the tunnel -------------------------------------------------
if [[ ! -f "$KEY" ]]; then
	echo "==> Generating tunnel SSH key at $KEY"
	ssh-keygen -t ed25519 -N "" -f "$KEY" -C "estonia-scraper-tunnel"
fi

echo
echo "============================================================"
echo "On the VPS, add this line to /home/tunnel/.ssh/authorized_keys :"
echo
echo "restrict,port-forwarding,permitlisten=\"127.0.0.1:5050\" $(cat "$KEY.pub")"
echo
echo "============================================================"
read -r -p "Press Enter once that line is saved on the VPS... " _

# --- shared password ------------------------------------------------------
read -r -p "Shared password for the app (blank = no password, not recommended for a public URL): " APP_PASSWORD
APP_USERNAME="team"
# Stable session-signing key so logins survive an app restart. Reuse the
# existing one if the agent is already installed.
EXISTING_PLIST="$LA/ee.estonia-scraper.app.plist"
APP_SECRET_KEY="$(
	[ -f "$EXISTING_PLIST" ] && /usr/bin/plutil -extract EnvironmentVariables.APP_SECRET_KEY raw "$EXISTING_PLIST" 2>/dev/null
)"
[ -n "$APP_SECRET_KEY" ] || APP_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"

# --- render + load launchd agents ---------------------------------------
render() {
	sed -e "s#__PROJECT_DIR__#${PROJECT_DIR}#g" \
	    -e "s#__HOME__#${HOME}#g" \
	    -e "s#__AUTOSSH__#${AUTOSSH}#g" \
	    -e "s#__VPS_HOST__#${VPS_HOST}#g" \
	    -e "s#__APP_USERNAME__#${APP_USERNAME}#g" \
	    -e "s#__APP_PASSWORD__#${APP_PASSWORD}#g" \
	    -e "s#__APP_SECRET_KEY__#${APP_SECRET_KEY}#g" \
	    "$1"
}

for name in ee.estonia-scraper.app ee.estonia-scraper.tunnel; do
	dest="$LA/$name.plist"
	render "$PROJECT_DIR/deploy/mac/$name.plist.template" > "$dest"
	chmod 600 "$dest"
	launchctl unload "$dest" 2>/dev/null || true
	launchctl load "$dest"
	echo "==> loaded $name"
done

echo
echo "Done. Give it a few seconds, then check:"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' -u ${APP_USERNAME}:<password> https://${DOMAIN}/"
echo
echo "Logs:  $PROJECT_DIR/logs/app.log  and  $PROJECT_DIR/logs/tunnel.log"
echo "Stop:  launchctl unload ~/Library/LaunchAgents/ee.estonia-scraper.{app,tunnel}.plist"
echo
echo "You can now stop the old Cloudflare watchdog if it's still running:"
echo "  pkill -f tunnel_watchdog.sh ; pkill -f 'cloudflared tunnel'"
