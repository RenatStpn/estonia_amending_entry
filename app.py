"""
Simple local web app: find Estonian companies (OÜ/UÜ/TÜ/AS) with an Amending
entry in a chosen period, filtered by yearly revenue.

Run with:
    python app.py
then open http://127.0.0.1:5050
"""
import os
import re
import uuid
from datetime import date, datetime, timedelta

import pandas as pd
from flask import Flask, render_template, request, send_file

from entries_search import LEGAL_FORM_VALUES, EntrySearchError, search_amending_entries
from revenue_data import build_revenue_map, list_available_years

app = Flask(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LEGAL_FORMS = list(LEGAL_FORM_VALUES.keys())  # AS, TÜ, UÜ, OÜ
FALLBACK_YEARS = list(range(2019, date.today().year))


def _iso_to_estonian(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")


@app.route("/", methods=["GET"])
def index():
    today = date.today()
    years = list_available_years() or FALLBACK_YEARS
    return render_template(
        "index.html",
        legal_forms=LEGAL_FORMS,
        selected_forms=LEGAL_FORMS,
        start_date=(today - timedelta(days=30)).isoformat(),
        end_date=today.isoformat(),
        years=years,
        selected_year=max(years),
        min_revenue="",
        max_revenue="",
        results=None,
        error=None,
        summary=None,
        log=None,
        download_token=None,
    )


@app.route("/search", methods=["POST"])
def search():
    start_date_iso = request.form.get("start_date", "").strip()
    end_date_iso = request.form.get("end_date", "").strip()
    selected_forms = request.form.getlist("legal_forms") or LEGAL_FORMS
    year = int(request.form.get("year"))
    min_revenue_raw = request.form.get("min_revenue", "").strip()
    max_revenue_raw = request.form.get("max_revenue", "").strip()

    years = list_available_years() or FALLBACK_YEARS

    log = []

    def progress(msg):
        log.append(msg)
        print(msg, flush=True)

    error = None
    results = []
    summary = None
    download_token = None

    try:
        min_revenue = float(min_revenue_raw) if min_revenue_raw else 0.0
        max_revenue = float(max_revenue_raw) if max_revenue_raw else float("inf")
        if min_revenue > max_revenue:
            raise ValueError("Minimum revenue cannot be greater than maximum revenue.")

        start_date = _iso_to_estonian(start_date_iso)
        end_date = _iso_to_estonian(end_date_iso)

        entries, total_found, truncated = search_amending_entries(
            start_date, end_date, selected_forms, progress_cb=progress
        )

        unique_entries = {}
        for e in entries:
            unique_entries.setdefault(e["registry_code"], e)
        unique_entries = list(unique_entries.values())
        progress(f"{len(unique_entries)} unique companies found with an amending entry in this period.")

        progress(f"Loading {year} revenue data (first run downloads reference data from rik.ee, please wait)...")
        revenue_map = build_revenue_map(year, progress_cb=progress)

        for e in unique_entries:
            rev = revenue_map.get(e["registry_code"])
            if rev is None:
                continue
            if min_revenue <= rev <= max_revenue:
                results.append({
                    "company_name": e["company_name"],
                    "registry_code": e["registry_code"],
                    "revenue": rev,
                    "entry_date": e["entry_date"],
                    "status": e["status"],
                    "url": f"https://ariregister.rik.ee/eng/company/{e['registry_code']}",
                })

        results.sort(key=lambda r: r["revenue"], reverse=True)

        summary = (
            f"{total_found} amending entries found in period"
            + (" (result set was capped — narrow the date range to see all of them)" if truncated else "")
            + f" → {len(unique_entries)} unique companies → {len(results)} within the chosen revenue range."
        )

        if results:
            df = pd.DataFrame(results)[
                ["company_name", "registry_code", "revenue", "entry_date", "status", "url"]
            ]
            df.columns = [
                "Company name", "Registry code", f"Revenue {year} (EUR)",
                "Amending entry date", "Status", "Register link",
            ]
            download_token = uuid.uuid4().hex
            df.to_excel(os.path.join(OUTPUT_DIR, f"{download_token}.xlsx"), index=False)

    except EntrySearchError as ex:
        error = f"Search failed: {ex}"
    except ValueError as ex:
        error = str(ex)
    except Exception as ex:  # keep the simple UI alive with a readable message
        error = f"Unexpected error: {ex}"

    return render_template(
        "index.html",
        legal_forms=LEGAL_FORMS,
        selected_forms=selected_forms,
        start_date=start_date_iso,
        end_date=end_date_iso,
        years=years,
        selected_year=year,
        min_revenue=min_revenue_raw,
        max_revenue=max_revenue_raw,
        results=results,
        error=error,
        summary=summary,
        log=log,
        download_token=download_token,
    )


@app.route("/download/<token>")
def download(token):
    if not re.match(r"^[a-f0-9]{32}$", token):
        return "Invalid download link", 400
    path = os.path.join(OUTPUT_DIR, f"{token}.xlsx")
    if not os.path.exists(path):
        return "File not found (it may have expired)", 404
    return send_file(path, as_attachment=True, download_name="estonia_companies.xlsx")


if __name__ == "__main__":
    app.run(debug=False, port=5050)
