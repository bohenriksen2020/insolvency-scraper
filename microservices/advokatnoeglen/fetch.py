#!/usr/bin/env python3
"""
Scrape Advokatnøglen for a list of names.

Input:
  - text file with one full name per line (UTF-8)

Output:
  - JSON Lines file (default: out_advokatnoeglen/results.jsonl)
    Each line is a JSON object with:
      {
        "query_name": "...",
        "results": [
          {
            "result_name": "...",
            "result_firm_str": "...",
            "profile_url": "https://www.advokatnoeglen.dk/advokat/<slug-guid>",
            "profile": {
              "name": "...",
              "title": "...",
              "areas": ["...","..."],
              "bar_year": 2004,
              "rights_landsret": true,
              "rights_hojesteret": false,
              "email": "name@example.com",        # decoded if present
              "firm": {
                "name": "...",
                "address_lines": ["line1", "line2", "country"],
                "zip": "8700",
                "city": "Horsens",
                "phone": "70101330",
                "email": "firm@example.com",     # decoded if present
                "cvr": "37158267",
                "website": "http://...",
                "court_district": "Horsens",
                "staff_count": 13
              }
            }
          },
          ...
        ]
      }
    ]
"""

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE = "https://www.advokatnoeglen.dk"
SEARCH_PATH = "/sog.aspx"
UA = "Mozilla/5.0 (compatible; AdvokatnoeglenScraper/1.0; +https://example.com/bot)"

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
    "Connection": "close",
    # Avoid getting blocked by simple checks
})

ROW_ONCLICK_RE = re.compile(r"location\.href\s*=\s*'(?P<href>[^']+)'")
SPACES = re.compile(r"\s+")
ZIP_CITY_RE = re.compile(r"^\s*(\d{4})\s+(.+)$")
STAFF_RE = re.compile(r"Ansatte advokater:\s*(\d+)")
CVR_RE = re.compile(r"Cvr-nr\.*:\s*([0-9]+)")
BOOL_JA_RE = re.compile(r"\bJa\b", re.IGNORECASE)
BOOL_NEJ_RE = re.compile(r"\bNej\b", re.IGNORECASE)

def clean_text(s: str) -> str:
    return SPACES.sub(" ", s).strip()

def decode_email_from_href(href: str) -> Optional[str]:
    """
    Advokatnøglen uses /email.aspx?e=<reversed-string>.
    We can decode by reversing the whole string.
    """
    try:
        qs = parse_qs(urlparse(href).query)
        e = qs.get("e", [None])[0]
        if not e:
            return None
        return e[::-1]  # reverse the whole string
    except Exception:
        return None

def parse_search_results(html: str) -> List[Dict]:
    """
    Returns list of {result_name, result_firm_str, profile_url}
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.grid.searchresults")
    out: List[Dict] = []
    if not table:
        return out

    rows = table.select("tr")
    if not rows or len(rows) <= 1:
        return out

    # Skip header row
    for tr in rows[1:]:
        # onclick="location.href='/advokat/<slug-guid>'"
        onclick = tr.get("onclick", "")
        m = ROW_ONCLICK_RE.search(onclick)
        href = m.group("href") if m else None
        if not href:
            # try a direct <a> if it exists (rare)
            link = tr.find("a")
            if link and link.get("href"):
                href = link["href"]

        tds = tr.find_all("td")
        name_txt = clean_text(tds[0].get_text(" ", strip=True)) if len(tds) > 0 else ""
        firm_txt = clean_text(tds[1].get_text(" ", strip=True)) if len(tds) > 1 else ""

        if href:
            out.append({
                "result_name": name_txt,
                "result_firm_str": firm_txt,
                "profile_url": urljoin(BASE, href),
            })

    return out

def extract_bool_from_line(line: str) -> Optional[bool]:
    if BOOL_JA_RE.search(line):
        return True
    if BOOL_NEJ_RE.search(line):
        return False
    return None

def parse_profile(html: str, url: str) -> Dict:
    """
    Parse a person profile page.
    """
    soup = BeautifulSoup(html, "html.parser")
    person = soup.select_one("div.person") or soup

    # Top header: name + title
    h1s = person.find_all("h1")
    name = clean_text(h1s[0].get_text(" ", strip=True)) if h1s else None

    # First section h2 often is "Advokat" (title)
    title = None
    h2s = person.find_all("h2")
    if h2s:
        # defensive: the first h2 under the top border block holds the title
        title = clean_text(h2s[0].get_text(" ", strip=True))

    # Areas: h2 containing "Arbejdsområder:"
    areas: List[str] = []
    for h2 in h2s:
        txt = clean_text(h2.get_text(" ", strip=True))
        if txt.lower().startswith("arbejdsområder:"):
            # Extract parts after colon; keep commas/slashes as separators
            after = txt.split(":", 1)[1].strip()
            # Normalize line breaks already coalesced; split by comma or slash or " / "
            parts = re.split(r"[,/]+", after)
            areas = [clean_text(p) for p in parts if clean_text(p)]
            break

    # Details paragraph with Beskikkelsesår / Møderet etc.
    details_p = None
    for p in person.select("p"):
        if "Beskikkelsesår" in p.get_text():
            details_p = p
            break

    bar_year = None
    rights_landsret = None
    rights_hojesteret = None
    email = None

    if details_p:
        # <br/> separated lines
        parts = [clean_text(x) for x in details_p.decode_contents().split("<br/>")]
        parts = [clean_text(BeautifulSoup(p, "html.parser").get_text(" ", strip=True)) for p in parts]
        for line in parts:
            if not line:
                continue
            low = line.lower()
            if "beskikkelsesår" in low:
                # digits at end
                m = re.search(r"(\d{4})", line)
                if m:
                    bar_year = int(m.group(1))
            elif "møderet for landsret" in low:
                rights_landsret = extract_bool_from_line(line)
            elif "møderet for højesteret" in low:
                rights_hojesteret = extract_bool_from_line(line)

        # Personal email link (first a[href^="/email.aspx"])
        a = details_p.select_one('a[href^="/email.aspx"]')
        if a and a.get("href"):
            email = decode_email_from_href(a["href"])

    # Firm box: the grey box with background style
    firm_block = None
    for div in person.select("div"):
        style = div.get("style", "")
        if "background" in style and "#f4f4f4" in style:
            firm_block = div
            break

    firm: Dict = {}
    if firm_block:
        # Firm name (h2)
        firm_name = None
        h2 = firm_block.find("h2")
        if h2:
            firm_name = clean_text(h2.get_text(" ", strip=True))

        ps = firm_block.find_all("p")
        # Address block: first <p>
        addr_lines: List[str] = []
        zip_code = None
        city = None
        if len(ps) >= 1:
            lines = [clean_text(x) for x in ps[0].get_text("\n", strip=True).splitlines() if clean_text(x)]
            # Try to parse zip & city on one line (like "8700 Horsens")
            for i, ln in enumerate(lines):
                m = ZIP_CITY_RE.match(ln)
                if m:
                    zip_code, city = m.group(1), m.group(2)
                    # lines before zip are street; after zip may be country
                    addr_lines = lines[:i] + lines[i+1:]
                    break
            if zip_code is None:
                addr_lines = lines

        # Contact block: second <p>
        phone = None
        firm_email = None
        cvr = None
        if len(ps) >= 2:
            # phone
            txt2 = ps[1].get_text(" ", strip=True)
            # Phone often appears as "Tlf.: 70101330"
            m = re.search(r"Tlf\.\s*:?\s*([0-9\s+]+)", txt2, re.IGNORECASE)
            if m:
                phone = clean_text(m.group(1))
            # CVR
            m = CVR_RE.search(txt2)
            if m:
                cvr = m.group(1)
            # email link
            a_firm = ps[1].select_one('a[href^="/email.aspx"]')
            if a_firm and a_firm.get("href"):
                firm_email = decode_email_from_href(a_firm["href"])

        # Footer block: third <p>
        website = None
        staff_count = None
        court_district = None
        if len(ps) >= 3:
            # Website is an <a>
            a_web = ps[2].find("a")
            if a_web and a_web.get("href"):
                website = a_web["href"].strip()
            txt3 = clean_text(ps[2].get_text(" ", strip=True))
            m = STAFF_RE.search(txt3)
            if m:
                staff_count = int(m.group(1))
            # Retskreds: <span> then text; we can search for "Retskreds:"
            m = re.search(r"Retskreds:\s*(.+)$", txt3)
            if m:
                court_district = clean_text(m.group(1))

        firm = {
            "name": firm_name,
            "address_lines": [ln for ln in addr_lines if ln],
            "zip": zip_code,
            "city": city,
            "phone": phone,
            "email": firm_email,
            "cvr": cvr,
            "website": website,
            "court_district": court_district,
            "staff_count": staff_count,
        }

    return {
        "name": name,
        "title": title,
        "areas": areas,
        "bar_year": bar_year,
        "rights_landsret": rights_landsret,
        "rights_hojesteret": rights_hojesteret,
        "email": email,
        "firm": firm if firm else None,
        "source_url": url,
    }

def search_name(name: str) -> Dict:
    """
    Perform the name search page and parse table rows.
    """
    params = {
        "s": "1",
        "t": "0",
        "name": name,
    }
    r = session.get(urljoin(BASE, SEARCH_PATH), params=params, timeout=30)
    r.raise_for_status()
    results = parse_search_results(r.text)
    return {"count": len(results), "results": results, "search_url": r.url}

def fetch_profile(url: str) -> Dict:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return parse_profile(r.text, url)

def run(names: List[str], out_jsonl: Path, sleep_between: float = 0.5):
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as f:
        for q in names:
            q = q.strip()
            if not q:
                continue
            try:
                search = search_name(q)
                enriched: List[Dict] = []
                for item in search["results"]:
                    url = item["profile_url"]
                    try:
                        prof = fetch_profile(url)
                        enriched.append({
                            **item,
                            "profile": prof,
                        })
                        time.sleep(sleep_between)
                    except Exception as ex:
                        enriched.append({
                            **item,
                            "error": f"{type(ex).__name__}: {ex}",
                        })
                row = {
                    "query_name": q,
                    "search_url": search["search_url"],
                    "results": enriched,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[✓] {q}: {len(enriched)} result(s)")
                time.sleep(sleep_between)
            except Exception as ex:
                row = {"query_name": q, "error": f"{type(ex).__name__}: {ex}"}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[x] {q}: {ex}")

def read_names_file(path: Path) -> List[str]:
    return [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines()]

def main():
    ap = argparse.ArgumentParser(description="Scrape Advokatnøglen by names.")
    ap.add_argument("names_file", help="UTF-8 text file with one full name per line")
    ap.add_argument("--out", default="out_advokatnoeglen/results.jsonl",
                    help="Output JSONL file (default: %(default)s)")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Sleep seconds between requests (default: %(default)s)")
    args = ap.parse_args()

    names = read_names_file(Path(args.names_file))
    run(names, Path(args.out), sleep_between=args.sleep)

if __name__ == "__main__":
    main()