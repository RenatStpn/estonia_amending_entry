"""
Find a company by (part of) its name, or by registry code, using the
e-Business Register's open "basic data" file (every company's name, code,
legal form and status, refreshed daily). Local and fast — no per-search
request to the register.
"""
import csv
import io
import os
import re
import threading
import time
import unicodedata
import zipfile

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_PATH = os.path.join(DATA_DIR, "company_names.csv")
URL = "https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed/ettevotja_rekvisiidid__lihtandmed.csv.zip"
USER_AGENT = "Mozilla/5.0 (compatible; EstoniaCompanyFinder/1.0)"
MAX_AGE_SECONDS = 24 * 3600

_lock = threading.Lock()
_companies = None        # list of dicts
_loaded_mtime = None
_refreshing = False


class CompanyLookupError(Exception):
    pass


def _norm(text):
    """Lowercase, drop diacritics (õ/ä/ö/ü -> o/a/o/u) and punctuation."""
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _download():
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        resp = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=120)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            data = z.read(z.namelist()[0])
    except (requests.RequestException, zipfile.BadZipFile) as ex:
        raise CompanyLookupError(f"Could not download the company list from rik.ee: {ex}") from ex
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, CSV_PATH)


def _parse():
    companies = []
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            name = row.get("nimi") or ""
            code = row.get("ariregistri_kood") or ""
            if not name or not code:
                continue
            companies.append({
                "name": name,
                "code": code,
                "norm": _norm(name),
                "form": row.get("ettevotja_oiguslik_vorm") or "",
                "status": row.get("ettevotja_staatus_tekstina") or "",
                "active": (row.get("ettevotja_staatus") or "") == "R",
            })
    return companies


def _refresh_in_background():
    global _refreshing
    with _lock:
        if _refreshing:
            return
        _refreshing = True

    def work():
        global _refreshing
        try:
            _download()
        except CompanyLookupError:
            pass
        finally:
            with _lock:
                _refreshing = False

    threading.Thread(target=work, daemon=True).start()


def _ensure_loaded():
    """Loads the list into memory (downloading it on first use) and reloads
    it when a fresher file has been fetched. Serves the old copy while a
    daily refresh runs in the background."""
    global _companies, _loaded_mtime
    with _lock:
        have_file = os.path.exists(CSV_PATH)
    if not have_file:
        _download()
    elif time.time() - os.path.getmtime(CSV_PATH) > MAX_AGE_SECONDS:
        _refresh_in_background()

    mtime = os.path.getmtime(CSV_PATH)
    with _lock:
        if _companies is not None and _loaded_mtime == mtime:
            return _companies
    parsed = _parse()
    with _lock:
        _companies, _loaded_mtime = parsed, mtime
    return parsed


def warm_up():
    """Load the list in the background at startup so the first search is fast."""
    def work():
        try:
            _ensure_loaded()
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()


def search(query, limit=25):
    """Returns up to `limit` companies matching `query`, best first.
    A 7-8 digit query is treated as a registry code."""
    query = (query or "").strip()
    if not query:
        return []
    companies = _ensure_loaded()

    digits = re.sub(r"\s+", "", query)
    if digits.isdigit() and 7 <= len(digits) <= 8:
        return [c for c in companies if c["code"] == digits][:limit]

    q = _norm(query)
    tokens = q.split()
    if not tokens:
        return []

    scored = []
    for c in companies:
        n = c["norm"]
        if not all(t in n for t in tokens):
            continue
        if n == q:
            rank = 0
        elif f" {q} " in f" {n} ":      # the query as whole word(s)
            rank = 1
        elif n.startswith(q):
            rank = 2
        else:
            rank = 3
        # Registered companies before deleted ones, then shorter names first.
        scored.append((rank, 0 if c["active"] else 1, len(n), c))
    scored.sort(key=lambda s: s[:3])
    return [s[3] for s in scored[:limit]]
