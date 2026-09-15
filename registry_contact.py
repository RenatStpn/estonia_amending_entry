"""
Looks up a company's registered phone number from its own page on
ariregister.rik.ee (the "Contacts" card on the company's print view),
for a batch of registry codes at once.
"""
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed

import requests
from bs4 import BeautifulSoup

BASE = "https://ariregister.rik.ee"
USER_AGENT = "Mozilla/5.0 (compatible; EstoniaCompanyFinder/1.0)"
_TELEPHONE_LABEL = re.compile(r"^\s*Telephone\s*$", re.I)

# requests' `timeout=` only bounds each individual socket read, not the
# whole request — a slow-trickling server can hang far longer than that.
# This pool exists purely to put a hard wall-clock cap on one HTTP call.
_HTTP_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="rik-http")
_HARD_TIMEOUT = 20  # seconds, wall-clock, no matter what


def get_phone(registry_code, session=None):
    """Returns the registered phone number for one company, or None if it
    doesn't have one listed (or the lookup fails)."""
    session = session or requests.Session()
    url = f"{BASE}/eng/company/{registry_code}/company_print_json"

    def _do_get():
        return session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)

    try:
        future = _HTTP_EXECUTOR.submit(_do_get)
        resp = future.result(timeout=_HARD_TIMEOUT)
        resp.raise_for_status()
    except (requests.RequestException, FutureTimeoutError):
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    label = soup.find("div", class_="text-muted", string=_TELEPHONE_LABEL)
    if not label:
        return None
    value = label.find_next_sibling("div")
    text = value.get_text(strip=True) if value else ""
    return text or None


def get_phones(registry_codes, max_workers=8, progress_cb=None):
    """Returns {registry_code: phone_or_None} for a batch of companies."""
    registry_codes = list(dict.fromkeys(registry_codes))  # de-dupe, keep order
    if not registry_codes:
        return {}

    session = requests.Session()
    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(get_phone, code, session): code for code in registry_codes
        }
        for future in as_completed(futures):
            code = futures[future]
            results[code] = future.result()
            done += 1
            if progress_cb and (done % 25 == 0 or done == len(registry_codes)):
                progress_cb(f"Checked phone numbers for {done}/{len(registry_codes)} companies...")
    return results
