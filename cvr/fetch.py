import argparse
import requests

BASE_URL = "https://datacvr.virk.dk"
CVR_SEARCH_URL = f"{BASE_URL}/gateway/soeg/fritekst"
COMPANY_URL = f"{BASE_URL}/gateway/virksomhed/hentVirksomhed"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/129.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE_URL + "/",
}

session = requests.Session()
session.headers.update(HEADERS)
session.get(BASE_URL)  # initialize cookies


def search_company(name: str):
    """Find CVR for a company under konkurs."""
    payload = {"fritekstCommand": {"soegOrd": name, "sideIndex": "0", "size": ["10"]}}
    r = session.post(CVR_SEARCH_URL, json=payload)
    r.raise_for_status()

    for e in r.json().get("enheder", []):
        if e.get("status") == "UNDERKONKURS":
            print(f"🏦 Found insolvent company: {e['senesteNavn']} ({e['cvr']})")
            return e["cvr"], e["senesteNavn"]

    print(f"⚠️ No company under konkurs found for '{name}'.")
    return None, None


def fetch_company_data(cvr: str):
    """Fetch full company data from hentVirksomhed."""
    url = f"{COMPANY_URL}?cvrnummer={cvr}&locale=da"
    r = session.get(url)
    if r.status_code == 403:
        print("🔁 Got 403, retrying after cookie refresh...")
        session.get(BASE_URL)
        r = session.get(url)
    r.raise_for_status()
    return r.json()


def find_latest_xbrl(company_data, cvr: str):
    """Find the latest regnskab with an XML (XBRL) dokument."""
    regnskaber = company_data.get("sammenhaengendeRegnskaber", [])
    if not regnskaber:
        print("⚠️ No regnskaber found for this company.")
        return None

    # Sort by year (latest first)
    latest = sorted(regnskaber, key=lambda r: r["regnskabsperiodeTil"], reverse=True)[0]
    regnskab = latest["regnskaber"][0]
    periode = regnskab.get("periodeFormateret", "?")
    print(f"🗓 Latest regnskab period: {periode}")

    # Find XBRL (XML) document
    for ref in regnskab.get("dokumentreferencer", []):
        if ref["indholdstype"].upper() == "XML":
            dokument_id = ref["dokumentId"]
            xbrl_url = f"{BASE_URL}/gateway/dokument/downloadDokumentForVirksomhed?dokumentId={dokument_id}&cvrNummer={cvr}"
            print(f"✅ Found XBRL document:\n{xbrl_url}")
            return xbrl_url

    print("⚠️ No XBRL (XML) document found in latest regnskab.")
    return None


def main():
    parser = argparse.ArgumentParser(description="Fetch latest XBRL report for insolvent Danish company.")
    parser.add_argument("--company", required=True, help="Company name to search for")
    args = parser.parse_args()

    cvr, name = search_company(args.company)
    if not cvr:
        return

    data = fetch_company_data(cvr)
    find_latest_xbrl(data, cvr)


if __name__ == "__main__":
    main()
