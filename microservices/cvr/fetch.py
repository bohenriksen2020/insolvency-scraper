#!/usr/bin/env python3
"""
Scrape CVR data from datacvr.virk.dk using a Chrome-like session
that passes Cloudflare's browser challenge automatically.
"""

import argparse
import xml.etree.ElementTree as ET
from io import BytesIO
import cloudscraper

BASE_URL = "https://datacvr.virk.dk"
CVR_SEARCH_URL = f"{BASE_URL}/gateway/soeg/fritekst"
COMPANY_URL = f"{BASE_URL}/gateway/virksomhed/hentVirksomhed"

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


class Fetch:
    def __init__(self):
        # Create a browser-like session (Cloudflare-safe)
        self.session = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "mobile": False,
            }
        )
        # Optional: preload cookies to look extra realistic
        self.session.get(BASE_URL)

    def search_company(self, name: str):
        payload = {"fritekstCommand": {"soegOrd": name, "sideIndex": "0", "size": ["10"]}}
        r = self.session.post(CVR_SEARCH_URL, json=payload)
        r.raise_for_status()
        print(f"search_company returned {r.json()}")
        for e in r.json().get("enheder", []):
            if e.get("status") in ["UNDERKONKURS", "OPLØSTEFTERKONKURS", "UNDERTVANGSOPLØSNING"] or e.get('cvr') is not None:
                print(f"🏦 Found insolvent company: {e['senesteNavn']} ({e['cvr']}), status: {e.get("status")}")
                return e["cvr"], e["senesteNavn"]
        print(f"⚠️ No company under konkurs found for '{name}'.")
        return None, None

    def fetch_company_data(self, cvr: str):
        url = f"{COMPANY_URL}?cvrnummer={cvr}&locale=da"
        r = self.session.get(url)
        r.raise_for_status()
        return r.json()

    def find_latest_xbrl(self, company_data, cvr: str):
        regnskaber = company_data.get("sammenhaengendeRegnskaber", [])
        if not regnskaber:
            print("⚠️ No regnskaber found for this company.")
            return None
        latest = sorted(regnskaber, key=lambda r: r["regnskabsperiodeTil"], reverse=True)[0]
        regnskab = latest["regnskaber"][0]
        periode = regnskab.get("periodeFormateret", "?")
        print(f"🗓 Latest regnskab period: {periode}")
        for ref in regnskab.get("dokumentreferencer", []):
            if ref["indholdstype"].upper() == "XML":
                dokument_id = ref["dokumentId"]
                url_gateway = (
                    f"{BASE_URL}/gateway/dokument/downloadDokumentForVirksomhed?"
                    f"dokumentId={dokument_id}&cvrNummer={cvr}"
                )
                url_public = f"{BASE_URL}/dokument/{dokument_id}"
                print(f"✅ Found XBRL document ID: {dokument_id}")
                return url_gateway, url_public
        print("⚠️ No XBRL (XML) document found in latest regnskab.")
        return None, None

    def download_xbrl(self, url_gateway: str, url_public: str):
        for url in (url_gateway, url_public):
            print(f"📥 Trying: {url}")
            r = self.session.get(url, allow_redirects=True)
            if r.status_code == 200 and "xml" in r.headers.get("Content-Type", "").lower():
                print("✅ Successfully downloaded XBRL XML.")
                return r.content
            elif r.status_code == 403:
                print("⚠️ Forbidden, trying next fallback...")
        return {"status" : "❌ Unable to download XBRL XML from any URL."}
        #raise RuntimeError("❌ Unable to download XBRL XML from any URL.")

    def parse_xbrl_assets(self, xml_content: bytes):
        tree = ET.parse(BytesIO(xml_content))
        root = tree.getroot()
        results = []
        for tag, name in ASSET_TAGS.items():
            local_tag = tag.split(":")[1]
            values = []
            for el in root.iter():
                if el.tag.endswith(local_tag):
                    try:
                        val = float(el.text.strip().replace(",", "."))
                        values.append(val)
                    except (ValueError, AttributeError):
                        continue
            if values:
                results.append((tag, name, max(values)))
        return results


def main():
    parser = argparse.ArgumentParser(description="Fetch and parse XBRL for an insolvent company.")
    parser.add_argument("--company", required=True)
    args = parser.parse_args()

    fetch = Fetch()
    cvr, name = fetch.search_company(args.company)
    if not cvr:
        return
    data = fetch.fetch_company_data(cvr)
    urls = fetch.find_latest_xbrl(data, cvr)
    if not urls:
        return
    xml = fetch.download_xbrl(*urls)
    assets = fetch.parse_xbrl_assets(xml)
    print("\n📊 Tangible Asset Overview:\n")
    print("| XBRL Field | English Name | Value (DKK) |")
    print("|-------------|--------------|--------------|")
    for tag, label, val in assets:
        print(f"| {tag} | {label} | {val:,.0f} |")


if __name__ == "__main__":
    main()
