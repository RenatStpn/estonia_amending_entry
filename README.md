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
