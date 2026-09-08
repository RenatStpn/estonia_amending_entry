import re
import time
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm
from playwright.sync_api import sync_playwright

BASE = "https://ariregister.rik.ee"
SEARCH_ID = "a8e3d4b"
START_URL = f"{BASE}/eng/company_search_result/{SEARCH_ID}?name_or_code="
MAX_PAGES = 200          # increase if needed
SLEEP_BETWEEN_PAGES = 1  # be polite
SLEEP_BETWEEN_COMPANIES = 0.8

ESTONIA_CC = "+372"

# ---------------------------
# Helpers
# ---------------------------

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def extract_first_e164_like(text: str) -> str:
    """
    Extract first phone number starting with + and digits/spaces/hyphens.
    Returns cleaned phone like '+44 20 1234 5678' (keeps spaces).
    """
    if not text:
        return ""
    # fairly strict: must start with + and at least 6 digits total
    m = re.search(r"(\+\d[\d\s\-\(\)]{5,})", text)
    if not m:
        return ""
    phone = clean(m.group(1))
    # Remove trailing punctuation
    phone = re.sub(r"[;,\.]+$", "", phone)
    return phone

def extract_country_code(phone: str) -> str:
    """
    Extract country calling code from a +E.164-like phone.
    Example: '+372 555 1234' -> '+372'
    """
    if not phone:
        return ""
    m = re.match(r"^\+(\d{1,3})", phone.strip())
    return f"+{m.group(1)}" if m else ""

def has_non_estonian_registry_phone(phone: str) -> bool:
    """
    Condition you want:
    - phone exists
    - starts with '+'
    - country code != +372
    """
    if not phone:
        return False
    if not phone.strip().startswith("+"):
        return False
    cc = extract_country_code(phone)
    if not cc:
        return False
    return cc != ESTONIA_CC

# ---------------------------
# Page parsing
# ---------------------------

def collect_companies_from_search_page(html: str) -> list[dict]:
    """
    From a search results page, collect unique companies by registry code.
    """
    soup = BeautifulSoup(html, "lxml")
    companies = {}

    # Company links look like: /eng/company/<code>/<slug>
    for a in soup.select('a[href^="/eng/company/"]'):
        href = a.get("href", "")
        name = clean(a.get_text())
        m = re.match(r"^/eng/company/(\d{5,10})/", href)
        if not m:
            continue

        code = m.group(1)
        companies[code] = {
            "registry_code": code,
            "company_name": name,
            "company_url": urljoin(BASE, href),
        }

    return list(companies.values())

def parse_company_print_json_html(html: str) -> dict:
    """
    Parse the 'company_print_json' HTML to extract:
    - company email (if present)
    - registry phone (ONLY from registry page)
    - website (optional)
    - director/board member name (best-effort)
    """
    soup = BeautifulSoup(html, "lxml")

    # EMAIL
    email = ""
    # Often in mailto links:
    for a in soup.select('a[href^="mailto:"]'):
        txt = clean(a.get_text())
        if "@" in txt:
            email = txt
            break

    # PHONE: look specifically for labeled fields, then extract +number
    phone = ""

    # Try to locate by labels: "Mobile phone", "Phone"
    label_candidates = ["Mobile phone", "Phone"]
    for label in label_candidates:
        node = soup.find(string=re.compile(rf"^{re.escape(label)}$", re.I))
        if not node:
            continue
        # Search nearby text for +number
        parent = node.parent
        nearby_text = clean(parent.get_text(" ", strip=True))
        phone = extract_first_e164_like(nearby_text)
        if phone:
            break

        # If not in same parent, look a bit forward
        forward_text = ""
        for nxt in parent.find_all_next(string=True, limit=40):
            forward_text += " " + clean(nxt)
        phone = extract_first_e164_like(forward_text)
        if phone:
            break

    # WEBSITE
    website = ""
    # Sometimes label is exactly: Internet address (www)
    web_label = soup.find(string=re.compile(r"^Internet address \(www\)$", re.I))
    if web_label:
        p = web_label.parent
        # grab next plausible domain-like chunk
        for s in p.find_all_next(string=True, limit=40):
            s2 = clean(s)
            if not s2:
                continue
            # crude domain heuristic
            if "." in s2 and "@" not in s2 and len(s2) < 120:
                if not any(x in s2.lower() for x in ["e-business", "register", "support", "download"]):
                    website = s2
                    break

    # DIRECTOR / BOARD MEMBER (best-effort)
    director = ""
    text_lines = soup.get_text("\n", strip=True).split("\n")
    # Look for section markers and then a name-like line
    section_markers = [
        "Management board",
        "Members of the management board",
        "Right of representation",
    ]
    for i, line in enumerate(text_lines):
        if any(m.lower() in line.lower() for m in section_markers):
            window = text_lines[i:i+60]
            for w in window:
                w = clean(w)
                # name heuristic: 2+ words with letters
                if re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ'\-]+(?: [A-Za-zÀ-ÖØ-öø-ÿ'\-]+){1,3}$", w):
                    director = w
                    break
            if director:
                break

    return {
        "company_email": email,
        "registry_phone": phone,  # IMPORTANT: registry-only
        "website": website,
        "director_name": director,
    }

# ---------------------------
# Main
# ---------------------------

def main():
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()

        # 1) Crawl search pages to get list of companies
        all_companies = {}
        for pg in range(1, MAX_PAGES + 1):
            url = START_URL if pg == 1 else f"{START_URL}&page={pg}"
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            html = page.content()

            companies = collect_companies_from_search_page(html)
            if not companies:
                print(f"[STOP] No companies found on page {pg}.")
                break

            for c in companies:
                all_companies[c["registry_code"]] = c

            print(f"[OK] Page {pg}: +{len(companies)} companies (unique total {len(all_companies)})")
            time.sleep(SLEEP_BETWEEN_PAGES)

        companies = list(all_companies.values())

        # 2) Enrich and FILTER: keep ONLY those with non-Estonian phone in registry
        kept = 0
        for c in tqdm(companies, desc="Checking registry phones"):
            code = c["registry_code"]
            print_url = f"{BASE}/eng/company/{code}/company_print_json"

            page.goto(print_url, wait_until="domcontentloaded", timeout=60000)
            detail_html = page.content()
            parsed = parse_company_print_json_html(detail_html)

            phone = parsed["registry_phone"]
            if not has_non_estonian_registry_phone(phone):
                # DROP anything missing phone OR Estonian phone OR no country code
                time.sleep(SLEEP_BETWEEN_COMPANIES)
                continue

            cc = extract_country_code(phone)
            kept += 1

            results.append({
                "Registry code": code,
                "Company name": c["company_name"],
                "Company email": parsed["company_email"],
                "Company phone (registry)": phone,
                "Phone country code": cc,
                "Director / board member full name": parsed["director_name"],
                "Company website": parsed["website"],
                "Source company_print_url": print_url,
                "Source company_url": c["company_url"],
            })

            # Save checkpoints so you don't lose everything if it dies
            if kept % 100 == 0:
                df_tmp = pd.DataFrame(results)
                df_tmp.to_excel("estonia_non_estonian_registry_phones_checkpoint.xlsx", index=False)
                print(f"[CHECKPOINT] Saved {kept} rows.")

            time.sleep(SLEEP_BETWEEN_COMPANIES)

        browser.close()

    df = pd.DataFrame(results)
    out_file = "estonia_non_estonian_registry_phones.xlsx"
    df.to_excel(out_file, index=False)
    print(f"[DONE] Saved: {out_file} | rows kept: {len(df)}")

if __name__ == "__main__":
    main()
