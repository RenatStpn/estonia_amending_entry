"""
Looks up a single company's international (by-country) revenue breakdown from
ssb.ee (STORYBOOK / Inforegister), on demand for one registry code at a time.

This mirrors the exact request ssb.ee's own company page makes for logged-out
visitors (POST to its WordPress admin-ajax endpoint), found in its public
tab_finantsid.js. No login or scraping of rendered pages is needed — it's the
same request a person clicking around the site would trigger.
"""
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from country_names import translate as translate_country_name

SSB_AJAX_URL = "https://ssb.ee/wp-admin/admin-ajax.php"
USER_AGENT = "Mozilla/5.0 (compatible; EstoniaCompanyFinder/1.0)"

# The "Müügitulu riikide lõikes" (sales revenue by country) block is
# report #3 within the finance tab's combined HTML fragment.
COUNTRY_REVENUE_MARKER = "financereport3_table"


class SsbLookupError(Exception):
    pass


def _fetch_finance_html(registry_code):
    headers = {
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {
        "action": "tab_finantsid_action",
        "tab": "finance_raport_html",
        "reg_code": str(registry_code),
    }
    try:
        resp = requests.post(SSB_AJAX_URL, headers=headers, data=data, timeout=30)
    except requests.RequestException as ex:
        raise SsbLookupError(f"Could not reach ssb.ee: {ex}") from ex

    if resp.status_code == 404:
        # ssb.ee doesn't have a page for this registry code at all.
        return None
    if not resp.ok:
        raise SsbLookupError(f"ssb.ee returned an unexpected response (HTTP {resp.status_code}).")
    return resp.text


def get_international_revenue(registry_code):
    """
    Returns:
      {
        "years": [2010, 2011, ..., 2026],
        "forecast_year": 2026,        # last year, which is a forecast, or None
        "rows": [{"title": "Müük kokku", "by_year": {2010: 123, ...}}, ...],
        "source_url": "https://ssb.ee/...",
      }
    or None if ssb.ee has no country-revenue breakdown for this company.
    """
    html = _fetch_finance_html(registry_code)
    if html is None:
        return None

    idx = html.find(COUNTRY_REVENUE_MARKER)
    if idx == -1:
        return None

    # The block's data is passed as the second argument to an IIFE:
    #   (($, inp) => $(document).ready(...))(jQuery, {"years": [...], ...});
    m = re.search(r"\}\)\)\(jQuery,\s*(\{.*?\})\);", html[idx:idx + 20000], re.S)
    if not m:
        return None

    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    wtbl = payload.get("wtbl", {})
    titles = wtbl.get("titles", [])
    tcontent = wtbl.get("tcontent", [])

    years = []
    for t in titles:
        # Years are ints except the forecast year, e.g. "2026 prognoos".
        if isinstance(t, int):
            years.append(t)
        else:
            m2 = re.match(r"(\d{4})", str(t))
            if m2:
                years.append(int(m2.group(1)))
    forecast_year = years[-1] if titles and not isinstance(titles[-1], int) else None

    rows = []
    for group in tcontent:
        for row in group:
            title_et = row.get("0", "")
            by_year = {int(k): v for k, v in row.items() if k != "0"}
            rows.append({
                "title": translate_country_name(title_et),
                "title_et": title_et,
                "by_year": by_year,
            })

    if not rows:
        return None

    return {
        "years": years,
        "forecast_year": forecast_year,
        "rows": rows,
        "source_url": f"https://ssb.ee/{registry_code}-x/finantsid-varad-prognoosid",
    }


def has_export_revenue(data):
    """Given a get_international_revenue() result, returns True if the
    company has ever reported non-Estonia ("Eksport kokku") revenue above
    zero, False if it has the row but it's always zero, or None if there's
    no export-revenue row to judge from at all."""
    if not data:
        return None
    for row in data["rows"]:
        if row["title_et"] == "Eksport kokku":
            return any((v or 0) > 0 for v in row["by_year"].values())
    return None


def check_export_revenue_bulk(registry_codes, max_workers=5, progress_cb=None):
    """Returns {registry_code: True/False/None} — whether each company has
    ever reported revenue from outside Estonia. None means unknown (no
    ssb.ee data for that company, or the lookup failed)."""
    registry_codes = list(dict.fromkeys(registry_codes))
    if not registry_codes:
        return {}

    def check_one(code):
        try:
            return has_export_revenue(get_international_revenue(code))
        except SsbLookupError:
            return None

    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_one, code): code for code in registry_codes}
        for future in as_completed(futures):
            code = futures[future]
            results[code] = future.result()
            done += 1
            if progress_cb and (done % 25 == 0 or done == len(registry_codes)):
                progress_cb(
                    f"Checked international revenue for {done}/{len(registry_codes)} companies..."
                )
    return results
