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
        """
        Parse XBRL XML and extract key asset/liability fields across
        Danish GAAP (danGAAP), IFRS, and other namespaces.
        Returns a list of dicts with tag, label, and numeric value (float).
        """
        if isinstance(xml_content, dict):  # fallback if download failed
            return []

        import re
        import xml.etree.ElementTree as ET
        from io import BytesIO

        try:
            tree = ET.parse(BytesIO(xml_content))
        except Exception as e:
            print(f"⚠️ Failed parsing XBRL XML: {e}")
            return []

        root = tree.getroot()
        results = []

        FIELD_MAP = {
            # Tangible assets
            "PropertyPlantAndEquipment": "Tangible assets (IFRS)",
            "TangibleFixedAssets": "Tangible assets (Danish GAAP)",
            "LandAndBuildings": "Land and buildings",
            "Buildings": "Buildings",
            "Vehicles": "Vehicles",
            "FixturesAndFittingsToolsAndEquipment": "Fixtures, fittings & tools",
            "OtherTangibleFixedAssets": "Other tangible fixed assets",

            # Intangible assets
            "IntangibleAssets": "Intangible assets",
            "Goodwill": "Goodwill",
            "DevelopmentCosts": "Development costs",

            # Inventories
            "Inventories": "Inventories",
            "RawMaterialsAndConsumables": "Raw materials & consumables",
            "FinishedGoodsAndGoodsForResale": "Finished goods & resale goods",

            # Liabilities & equity
            "Equity": "Equity",
            "Provisions": "Provisions",
            "LongTermDebt": "Long-term debt",
            "ShortTermDebt": "Short-term debt",
            "CurrentLiabilities": "Current liabilities",
            "TotalLiabilitiesAndEquity": "Liabilities + Equity (total)",
        }

        def to_float(value: str):
            """Convert number-like strings to float safely."""
            if not value:
                return None
            cleaned = re.sub(r"[^\d,.\-]", "", value).replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None

        for key, label in FIELD_MAP.items():
            numbers = []
            for el in root.iter():
                if el.tag.endswith(key):
                    num = to_float(el.text.strip() if el.text else "")
                    if isinstance(num, (float, int)) and num != 0:
                        numbers.append(num)
            if numbers:
                results.append({
                    "tag": key,
                    "label": label,
                    "value": float(max(numbers)),  # ensure float type
                })

        order = [
            "Tangible assets (Danish GAAP)", "Tangible assets (IFRS)",
            "Land and buildings", "Buildings", "Vehicles",
            "Fixtures, fittings & tools", "Other tangible fixed assets",
            "Intangible assets", "Goodwill", "Development costs",
            "Inventories", "Raw materials & consumables", "Finished goods & resale goods",
            "Equity", "Provisions", "Long-term debt", "Short-term debt",
            "Current liabilities", "Liabilities + Equity (total)"
        ]
        results.sort(key=lambda x: order.index(x["label"]) if x["label"] in order else len(order))
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
    print(xml)
    assets = fetch.parse_xbrl_assets(xml)
    print("\n📊 Tangible Asset Overview:\n")
    print("| XBRL Field | English Name | Value (DKK) |")
    print("|-------------|--------------|--------------|")
    for item in assets:
        tag = item.get("tag", "")
        label = item.get("label", "")
        val = item.get("value", "")
        if isinstance(val, (int, float)):
            print(f"| {tag} | {label} | {val:,.0f} |")
        else:
            print(f"| {tag} | {label} | {val} |")



if __name__ == "__main__":
    main()
