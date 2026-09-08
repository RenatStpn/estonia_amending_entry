"""
Downloads and caches ariregister.rik.ee's open annual-report data
(https://avaandmed.ariregister.rik.ee) and builds a {registry_code: revenue}
map for a given report year, so amending-entry results can be filtered by
yearly revenue.
"""
import json
import os
import re
import zipfile

import pandas as pd
import requests

OPEN_DATA_BASE = "https://avaandmed.ariregister.rik.ee"
DOWNLOAD_PAGE = f"{OPEN_DATA_BASE}/en/downloading-open-data"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

GENERAL_INFO_PATTERN = re.compile(r'href="(/sites/default/files/1\.aruannete_yldandmed[^"]*\.zip)"')
KEY_INDICATORS_PATTERN = re.compile(r'href="(/sites/default/files/4\.(\d{4})_aruannete_elemendid[^"]*\.zip)"')

CHUNK_SIZE = 300_000


class RevenueDataError(Exception):
    pass


def _download_page_html():
    resp = requests.get(DOWNLOAD_PAGE, timeout=60)
    resp.raise_for_status()
    return resp.text


def list_available_years():
    try:
        html = _download_page_html()
        years = sorted({int(y) for _, y in KEY_INDICATORS_PATTERN.findall(html)})
        return years
    except Exception:
        return []


def _download_and_extract(url, cache_name, progress_cb=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    csv_path = os.path.join(DATA_DIR, cache_name + ".csv")
    if os.path.exists(csv_path):
        return csv_path

    zip_path = os.path.join(DATA_DIR, cache_name + ".zip")
    if progress_cb:
        progress_cb(f"Downloading {cache_name} data set from e-Business Register open data...")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)

    if progress_cb:
        progress_cb(f"Extracting {cache_name}...")
    with zipfile.ZipFile(zip_path) as z:
        inner_name = z.namelist()[0]
        z.extract(inner_name, DATA_DIR)
    os.replace(os.path.join(DATA_DIR, inner_name), csv_path)
    os.remove(zip_path)
    return csv_path


def get_general_info_csv(force_refresh=False, progress_cb=None):
    cache_name = "general_info"
    csv_path = os.path.join(DATA_DIR, cache_name + ".csv")
    if force_refresh and os.path.exists(csv_path):
        os.remove(csv_path)
    if os.path.exists(csv_path):
        return csv_path

    html = _download_page_html()
    m = GENERAL_INFO_PATTERN.search(html)
    if not m:
        raise RevenueDataError("Could not find the annual reports general-info data set on rik.ee.")
    url = OPEN_DATA_BASE + m.group(1)
    return _download_and_extract(url, cache_name, progress_cb=progress_cb)


def get_key_indicators_csv(year, force_refresh=False, progress_cb=None):
    cache_name = f"key_indicators_{year}"
    csv_path = os.path.join(DATA_DIR, cache_name + ".csv")
    if force_refresh and os.path.exists(csv_path):
        os.remove(csv_path)
    if os.path.exists(csv_path):
        return csv_path

    html = _download_page_html()
    url = None
    for href, y in KEY_INDICATORS_PATTERN.findall(html):
        if y == str(year):
            url = OPEN_DATA_BASE + href
            break
    if not url:
        raise RevenueDataError(f"No key-indicators data set found for report year {year}.")
    return _download_and_extract(url, cache_name, progress_cb=progress_cb)


def build_revenue_map(year, force_refresh=False, progress_cb=None):
    """Returns {registry_code: revenue_eur} for the given annual report year."""

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    cache_json = os.path.join(DATA_DIR, f"revenue_map_{year}.json")
    if not force_refresh and os.path.exists(cache_json):
        log(f"Using cached {year} revenue data...")
        with open(cache_json, encoding="utf-8") as f:
            return json.load(f)

    general_csv = get_general_info_csv(force_refresh=force_refresh, progress_cb=log)
    ki_csv = get_key_indicators_csv(year, force_refresh=force_refresh, progress_cb=log)

    log(f"Matching companies to their {year} annual report...")
    code_to_latest_report = {}
    year_str = str(year)
    usecols = ["report_id", "registrikood", "aruandeaasta"]
    for chunk in pd.read_csv(general_csv, sep=";", usecols=usecols, dtype=str, chunksize=CHUNK_SIZE):
        sub = chunk[chunk["aruandeaasta"] == year_str]
        for rid, code in zip(sub["report_id"], sub["registrikood"]):
            prev = code_to_latest_report.get(code)
            if prev is None or int(rid) > int(prev):
                code_to_latest_report[code] = rid
    report_to_code = {rid: code for code, rid in code_to_latest_report.items()}

    log(f"Reading {year} revenue figures...")
    revenue = {}
    usecols2 = ["report_id", "elemendi_nimetus", "vaartus"]
    for chunk in pd.read_csv(ki_csv, sep=";", usecols=usecols2, dtype=str, chunksize=CHUNK_SIZE):
        sub = chunk[chunk["elemendi_nimetus"] == "Revenue"]
        for rid, val in zip(sub["report_id"], sub["vaartus"]):
            code = report_to_code.get(rid)
            if code is None:
                continue
            try:
                revenue[code] = float(val)
            except ValueError:
                continue

    with open(cache_json, "w", encoding="utf-8") as f:
        json.dump(revenue, f)
    log(f"Loaded revenue figures for {len(revenue)} companies for {year}.")
    return revenue
