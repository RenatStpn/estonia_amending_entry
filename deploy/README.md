# Team deployment — Mac app + VPS relay

Goal: your team opens `https://estonia.yourdomain.com` from locked-down
work laptops. Corporate proxies block tunnel services (Cloudflare, ngrok,
…), so we don't use one — instead a tiny VPS you control serves an
ordinary HTTPS website on your own domain and forwards requests to the
app running on the Mac over an outbound SSH tunnel.

```
work laptop ──HTTPS──▶ estonia.yourdomain.com (VPS: Caddy)
                              │  reverse SSH tunnel (Mac dials out)
                              ▼
                        Mac: Flask app on 127.0.0.1:5050
                              │
                              ├─▶ ariregister.rik.ee   (entry search)
                              ├─▶ avaandmed.ariregister.rik.ee (revenue CSVs)
                              └─▶ ssb.ee                (international revenue)
```

Nothing is exposed on the Mac or your home network — the Mac only makes
an outbound SSH connection. The VPS never holds the data; it just relays.

## You need

- A small VPS (1 vCPU / 1 GB is plenty) — Hetzner CX22 (~€4/mo),
  DigitalOcean, Vultr, etc. Ubuntu 22.04 or 24.04.
- A domain, with the ability to add a DNS record.
- The Mac left powered on, awake, and online (System Settings → Lock
  Screen / Energy: never sleep on power; or `caffeinate`). If the Mac is
  off, the site shows an "offline right now" page until it's back.

## One-time setup

### 1. DNS

Add an **A record**: `estonia` (or any subdomain) → your VPS's public IP.
Wait until `dig +short estonia.yourdomain.com` returns that IP.

### 2. VPS

Copy this repo's `deploy/vps/setup-vps.sh` to the VPS and run:

```bash
sudo bash setup-vps.sh estonia.yourdomain.com
```

It installs Caddy (automatic HTTPS), writes the Caddyfile, creates a
restricted `tunnel` user, and tightens sshd so dead tunnels are dropped
fast. It finishes by telling you to paste in the Mac's tunnel key —
do that in step 3.

### 3. Mac

From the project directory:

```bash
# once, if not already there:
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
brew install autossh

deploy/mac/install-mac.sh estonia.yourdomain.com <VPS_IP_OR_HOST>
```

The script:

- generates `~/.ssh/estonia_scraper_tunnel` and prints the exact
  `authorized_keys` line — paste it into `/home/tunnel/.ssh/authorized_keys`
  on the VPS, then press Enter to continue;
- asks for a shared password (used as HTTP Basic auth, username `team`);
- installs two launchd agents that start now, on login, and after a
  crash:
  - `ee.estonia-scraper.app` — the Flask app on `127.0.0.1:5050`
  - `ee.estonia-scraper.tunnel` — the autossh reverse tunnel to the VPS

### 4. Check

```bash
curl -s -o /dev/null -w '%{http_code}\n' -u team:<password> https://estonia.yourdomain.com/
```

`200` means you're live. Share the URL + the `team` / `<password>`
credentials with your team.

Then stop the old Cloudflare tunnel if it's still running:

```bash
pkill -f tunnel_watchdog.sh ; pkill -f 'cloudflared tunnel'
```

## Day-to-day

| Task | Command |
| --- | --- |
| Logs (app) | `tail -f logs/app.log` |
| Logs (tunnel) | `tail -f logs/tunnel.log` |
| Restart app | `launchctl kickstart -k gui/$(id -u)/ee.estonia-scraper.app` |
| Restart tunnel | `launchctl kickstart -k gui/$(id -u)/ee.estonia-scraper.tunnel` |
| Stop everything | `launchctl unload ~/Library/LaunchAgents/ee.estonia-scraper.{app,tunnel}.plist` |
| Deploy code change | `git pull` on the Mac, then restart the app (above) |
| Change the password | edit `APP_PASSWORD` in `~/Library/LaunchAgents/ee.estonia-scraper.app.plist`, then restart the app |

## Troubleshooting

- **502 / "offline right now"** — the Mac or the tunnel is down. Check
  `logs/tunnel.log`; `launchctl list | grep estonia` should show both
  agents. On the VPS, `sudo ss -tlnp | grep 5050` should show sshd
  listening on `127.0.0.1:5050`.
- **Cert not issued** — the A record must resolve to the VPS *before*
  Caddy runs; `sudo systemctl reload caddy` to retry, `journalctl -u caddy`
  for details.
- **Tunnel reconnect loops with "remote port forwarding failed"** — the
  old connection's socket hasn't been reaped yet; the sshd
  `ClientAliveInterval` from `setup-vps.sh` clears it within ~90s and
  autossh reconnects on its own.
- **Corporate proxy still blocks the domain** — a brand-new domain can
  land in "uncategorized". Ask IT to allow that one host, or use a
  subdomain of a domain your company already trusts.
