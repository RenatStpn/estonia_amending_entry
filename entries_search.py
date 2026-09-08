"""
Searches "Entries" (kanded) on ariregister.rik.ee — e.g. all Amending entries
for a chosen legal form and period — using plain HTTP requests (no browser
needed; the site's search form posts directly and renders results server-side).
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

BASE = "https://ariregister.rik.ee"
ENTRY_URL = f"{BASE}/eng/company_entry"

# Values of the underlying <select> options on the search form.
LEGAL_FORM_VALUES = {
    "AS": "1",   # Public limited company
    "TÜ": "2",   # General partnership
    "UÜ": "4",   # Limited partnership
    "OÜ": "5",   # Private limited company
}

# "Amending entry" (Muutmiskanne) for companies/commercial register.
AMENDING_ENTRY_TYPE_VALUE = "12"

RESULTS_PER_PAGE = 50
USER_AGENT = "Mozilla/5.0 (compatible; EstoniaCompanyFinder/1.0)"


class EntrySearchError(Exception):
    pass


def _new_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _get_form_token(session):
    resp = session.get(ENTRY_URL, timeout=30)
    resp.raise_for_status()
    m = re.search(r'name="_cft"[^>]*value="([^"]*)"', resp.text)
    if not m:
        raise EntrySearchError("Could not find the search form's security token; the site may have changed.")
    return m.group(1)


def _submit_search(session, cft, start_date, end_date, legal_forms):
    data = [
        ("_cft", cft),
        ("search", "1"),
        ("s__entry_type", AMENDING_ENTRY_TYPE_VALUE),
        ("s__period_start", start_date),
        ("s__period_end", end_date),
    ]
    for lf in legal_forms:
        value = LEGAL_FORM_VALUES.get(lf)
        if value:
            data.append(("s__company_legal_form", value))

    resp = session.post(
        ENTRY_URL, data=data, headers={"Referer": ENTRY_URL}, allow_redirects=False, timeout=30
    )
    if resp.status_code not in (302, 303):
        raise EntrySearchError(f"Unexpected response submitting the search (HTTP {resp.status_code}).")
    location = resp.headers.get("Location", "")
    m = re.search(r"search_id=([a-z0-9]+)", location)
    if not m:
        raise EntrySearchError("The search did not return a result set; check the dates and try again.")
    return m.group(1)


def _total_count(html):
    m = re.search(r"Search results\s*\(\s*([\d\s]+)\s*\)", html)
    if not m:
        return 0
    return int(m.group(1).replace(" ", ""))


def _parse_results_page(html):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="table-sm")
    rows = []
    if not table:
        return rows
    trs = table.find_all("tr")[2:]  # first two rows are headers
    for tr in trs:
        tds = tr.find_all("td")
        if len(tds) < 13:
            continue
        rows.append({
            "entry_type": tds[4].get_text(strip=True),
            "entry_date": tds[5].get_text(strip=True),
            "company_name": tds[10].get_text(strip=True),
            "registry_code": tds[11].get_text(strip=True),
            "status": tds[12].get_text(strip=True),
        })
    return rows


def search_amending_entries(
    start_date, end_date, legal_forms, max_pages=400, progress_cb=None, max_workers=5
):
    """
    start_date, end_date: strings formatted dd.mm.yyyy
    legal_forms: iterable of codes among AS, TÜ, UÜ, OÜ

    Returns (rows, total_count, truncated)
    """
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    session = _new_session()
    log("Opening search form on ariregister.rik.ee...")
    cft = _get_form_token(session)

    log("Submitting search (Amending entry, chosen legal forms and period)...")
    search_id = _submit_search(session, cft, start_date, end_date, legal_forms)

    first_url = f"{ENTRY_URL}?search_id={search_id}"
    resp = session.get(first_url, timeout=30)
    resp.raise_for_status()
    total = _total_count(resp.text)
    first_page_rows = _parse_results_page(resp.text)

    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE if total else 0
    truncated = total_pages > max_pages
    pages_to_fetch = min(total_pages, max_pages)

    log(
        f"Found {total} matching entries across {total_pages} page(s)"
        + (f" — fetching first {pages_to_fetch} pages (narrow the date range to see all)" if truncated else "")
        + "."
    )

    page_results = {1: first_page_rows}

    if pages_to_fetch > 1:
        def fetch_page(page_num):
            url = f"{ENTRY_URL}?search_id={search_id}&page={page_num}"
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return page_num, _parse_results_page(r.text)

        done = 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_page, p): p for p in range(2, pages_to_fetch + 1)}
            for future in as_completed(futures):
                page_num, rows = future.result()
                page_results[page_num] = rows
                done += 1
                if done % 20 == 0 or done == pages_to_fetch:
                    log(f"Fetched {done}/{pages_to_fetch} pages of entries...")

    all_rows = []
    for p in range(1, pages_to_fetch + 1):
        all_rows.extend(page_results.get(p, []))

    return all_rows, total, truncated
