# Running via a Cloudflare Tunnel from the Mac (current setup)

The app runs on the Mac (launchd `ee.estonia-scraper.app`) and a named Cloudflare
Tunnel (`estonia-finder`, launchd `ee.estonia-scraper.cftunnel`) connects it to
`https://estonianamendingentry.xyz`. DNS is on Cloudflare (free plan); the domain is
registered at Porkbun with Cloudflare's nameservers. No VPS is involved.

Setup that was done (one time):

    cloudflared tunnel login                       # authorize the zone
    cloudflared tunnel create estonia-finder
    cloudflared tunnel route dns estonia-finder estonianamendingentry.xyz
    # ~/.cloudflared/config.yml: ingress hostname -> http://127.0.0.1:5050
    # launchd agent runs: cloudflared tunnel --config ~/.cloudflared/config.yml run estonia-finder

Operations:

    tail -f logs/cftunnel.log
    launchctl kickstart -k gui/$(id -u)/ee.estonia-scraper.cftunnel   # restart tunnel
    launchctl kickstart -k gui/$(id -u)/ee.estonia-scraper.app        # restart app

To move off the Mac later, install cloudflared on an always-free VM
(see README.md here) and run the same tunnel there with the same credentials file.
Searches run as background jobs, so Cloudflare's ~100 s request limit doesn't apply.
