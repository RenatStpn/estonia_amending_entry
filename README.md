# Estonia Company Finder

A local Flask application for finding Estonian companies with an **Amending entry** in the e-Business Register during a selected period, then filtering the results by yearly revenue.

## What it does

- Searches the e-Business Register for Amending entries.
- Filters by legal form: `OÜ`, `UÜ`, `TÜ`, or `AS`.
- Matches companies against annual-report revenue data for a chosen year.
- Displays matching companies and exports them to Excel.

## Run locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5050>.

On the first search, the app downloads and caches the e-Business Register's open annual-report data in `data/`; this can take a while and uses substantial disk space. Search exports are written to `output/`. Neither directory is committed to Git.

## International revenue check

Each result row links to a by-country revenue breakdown (domestic vs. export, per country) pulled from ssb.ee. Country names are translated to English. This is third-party data, not the official register.

## Optional password

Set `APP_PASSWORD` (and optionally `APP_USERNAME`, default `team`) in the environment to require HTTP Basic auth for the whole app. Leave it unset for open local use.

## Sharing with a team

To let a team reach the app from locked-down laptops (where tunnel services like Cloudflare/ngrok are blocked), see [`deploy/README.md`](deploy/README.md): the app stays on the Mac and a small VPS you control serves it over HTTPS on your own domain via an outbound SSH tunnel.
