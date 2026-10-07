# Free hosting: Oracle Always Free VM + Cloudflare Tunnel

Replaces the paid VPS + SSH tunnel (see `../README.md`). The app runs on an
always-on free VM; Cloudflare provides DNS, HTTPS and a tunnel for free. The VM
needs **no open inbound ports** — `cloudflared` dials out to Cloudflare.

```
browser ─HTTPS─▶ Cloudflare (DNS + TLS) ─tunnel─▶ VM: cloudflared ─▶ gunicorn :5050
```

Why not Cloudflare Pages/Workers alone: they host static files / tiny scripts.
This app runs Python per request (scraping, pandas on ~500 MB of data), so it
needs a real VM; Cloudflare just fronts it.

## 1. Free VM (Oracle Cloud)

1. Create an Oracle Cloud account (needs a card for verification; Always Free
   resources stay free).
2. Compute → Create instance: image **Ubuntu 24.04**, shape **VM.Standard.A1.Flex**
   (Ampere ARM, e.g. 2 OCPU / 12 GB) — or the AMD micro shape if ARM capacity is
   unavailable. Add your SSH public key. No inbound rules needed beyond SSH.
3. **Upgrade the account to Pay As You Go** (you are still charged $0 within the
   free limits). Oracle reclaims *idle* Always Free instances on non-upgraded
   accounts, and this app is mostly idle.

## 2. Put the domain on Cloudflare (free)

1. Cloudflare dashboard → Add a site → `estonianamendingentry.xyz` → Free plan.
2. Cloudflare shows two nameservers. At Porkbun → Domain → Authoritative
   Nameservers, replace them with those two. Wait until Cloudflare says Active.
3. Delete the old `A` record pointing at the Hostman VPS (the tunnel creates its own).

## 3. Install the app on the VM

```bash
ssh ubuntu@<VM_IP>
curl -fsSL https://raw.githubusercontent.com/RenatStpn/estonia_amending_entry/main/deploy/cloudflare/setup-server.sh -o setup-server.sh
sudo bash setup-server.sh
```

It installs the app as a systemd service (auto-start, auto-restart) and
cloudflared. To require a login, set `APP_PASSWORD` in `/etc/estonia-finder.env`
and `sudo systemctl restart estonia-finder`.

## 4. Create the tunnel

Cloudflare dashboard → **Zero Trust → Networks → Tunnels → Create a tunnel**
(Cloudflared). It shows an install command containing a token. Run it on the VM:

```bash
sudo cloudflared service install <TOKEN>
```

Then **Public hostname**: `estonianamendingentry.xyz` → Service `HTTP` →
`localhost:5050`. Treat the token like a password; don't paste it in chats.

## 5. Cut over

Open https://estonianamendingentry.xyz. Once it works, stop the Mac agents and
delete the Hostman server to stop paying:

```bash
launchctl unload ~/Library/LaunchAgents/ee.estonia-scraper.{app,tunnel}.plist
```

The first search for a year downloads ~500 MB of reference data on the VM and is
slow once; after that it's cached in `/opt/estonia_amending_entry/data`.

## Operations

| Task | Command |
| --- | --- |
| Logs | `journalctl -u estonia-finder -f` |
| Restart | `sudo systemctl restart estonia-finder` |
| Update | `cd /opt/estonia_amending_entry && sudo -u finder git pull && sudo systemctl restart estonia-finder` |
| Tunnel status | `systemctl status cloudflared` |
