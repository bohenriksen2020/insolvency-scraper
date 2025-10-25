import argparse
import requests
import xml.etree.ElementTree as ET
from io import BytesIO

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


ASSET_TAGS = {
    "e:FixturesAndFittingsToolsAndEquipment": "Fixtures, fittings, tools and equipment",
    "e:OtherTangibleFixedAssets": "Other tangible fixed assets",
    "e:Inventories": "Inventories",
    "fsa:RawMaterialsAndConsumables": "Inventories (Raw materials and consumables)",
    "fsa:FinishedGoodsAndGoodsForResale": "Inventories (Finished goods and resale)",
    "e:LandAndBuildings": "Land and buildings",
    "e:Vehicles": "Vehicles",
    "e:TangibleFixedAssets": "Tangible fixed assets, total",
}


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
            url_gateway = f"{BASE_URL}/gateway/dokument/downloadDokumentForVirksomhed?dokumentId={dokument_id}&cvrNummer={cvr}"
            url_public = f"{BASE_URL}/dokument/{dokument_id}"
            print(f"✅ Found XBRL document ID: {dokument_id}")
            return url_gateway, url_public

    print("⚠️ No XBRL (XML) document found in latest regnskab.")
    return None, None


def download_xbrl(url_gateway: str, url_public: str):
    """Try to download XML via gateway first, fallback to public /dokument URL."""
    urls = [url_gateway, url_public]

    for url in urls:
        print(f"📥 Trying: {url}")
        r = session.get(url, allow_redirects=True)
        if r.status_code == 200 and "xml" in r.headers.get("Content-Type", "").lower():
            print("✅ Successfully downloaded XBRL XML.")
            return r.content
        elif r.status_code == 403:
            print("⚠️ Forbidden, trying next fallback...")
            continue

    raise RuntimeError("❌ Unable to download XBRL XML from any URL.")


def parse_xbrl_assets(xml_content: bytes):
    """Extract tangible asset fields from XBRL XML."""
    tree = ET.parse(BytesIO(xml_content))
    root = tree.getroot()

    results = []

    for tag, name in ASSET_TAGS.items():
        local_tag = tag.split(":")[1]
        values = []
        for el in root.iter():
            if el.tag.endswith(local_tag):
                try:
                    value = float(el.text.strip().replace(",", "."))
                    values.append(value)
                except (ValueError, AttributeError):
                    continue

        if values:
            results.append((tag, name, max(values)))

    return results


def main():
    parser = argparse.ArgumentParser(description="Fetch and parse latest XBRL for an insolvent Danish company.")
    parser.add_argument("--company", required=True, help="Company name to search for")
    args = parser.parse_args()

    cvr, name = search_company(args.company)
    if not cvr:
        return

    data = fetch_company_data(cvr)
    url_gateway, url_public = find_latest_xbrl(data, cvr)
    if not url_gateway:
        return

    xml_data = download_xbrl(url_gateway, url_public)
    assets = parse_xbrl_assets(xml_data)

    print("\n📊 Tangible Asset Overview:\n")
    print("| XBRL Field | English Name | Value (DKK) |")
    print("|-------------|--------------|--------------|")
    for tag, name, value in assets:
        print(f"| {tag} | {name} | {value:,.0f} |")


if __name__ == "__main__":
    main()