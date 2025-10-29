#!/usr/bin/env python3
"""
Scrape CVR data from datacvr.virk.dk using a Chrome-like session
that passes Cloudflare's browser challenge automatically.
"""

import argparse
import xml.etree.ElementTree as ET
from io import BytesIO
import cloudscraper
import re 
BASE_URL = "https://datacvr.virk.dk"
CVR_SEARCH_URL = f"{BASE_URL}/gateway/soeg/fritekst"
COMPANY_URL = f"{BASE_URL}/gateway/virksomhed/hentVirksomhed"

ASSET_TAGS = {
    "e:FixturesAndFittingsToolsAndEquipment": "Fixtures, fittings, tools and equipment",
    "e:FixturesFittingsToolsAndEquipment": "Fixtures, fittings, tools and equipment",
    "e:PropertyPlantAndEquipment": "Property, plant and equipment (total)",
    "e:OtherTangibleFixedAssets": "Other tangible fixed assets",
    "e:LandAndBuildings": "Land and buildings",
    "e:Vehicles": "Vehicles",
    "e:Inventories": "Inventories",
    "e:RawMaterialsAndConsumables": "Inventories (raw materials and consumables)",
    "e:FinishedGoodsAndGoodsForResale": "Inventories (finished goods and goods for resale)",
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
            status = (e.get("status") or "").upper()
            insolvent_states = [
                "UNDERKONKURS",
                "OPLØSTEFTERKONKURS",
                "UNDERTVANGSOPLØSNING",
                "UNDERLIKVIDATION",
                "UNDER FRIVILLIG LIKVIDATION",
                "LIKVIDATION",
                "UNDERREKONSTRUKTION",
            ]

            if any(s in status for s in insolvent_states):
                print(f"🏦 Found matching company: {e['senesteNavn']} ({e['cvr']}), status: {status}")
                return e["cvr"], e["senesteNavn"]
        # Retry stripped name (remove "under likvidation" etc.)
        clean_name = re.sub(r"\b(under|i|efter)\s+\w+", "", name, flags=re.IGNORECASE).strip()
        if clean_name != name:
            print(f"🔁 Retrying search with cleaned name: '{clean_name}'")
            return self.search_company(clean_name)            
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
        """Extract asset fields from XBRL XML using ASSET_TAGS."""
        if isinstance(xml_content, dict):
            return []

        try:
            tree = ET.parse(BytesIO(xml_content))
        except Exception as e:
            print(f"⚠️ Failed parsing XBRL XML: {e}")
            return []

        root = tree.getroot()
        results = []

        def to_float(value: str):
            if not value:
                return None
            cleaned = re.sub(r"[^\d,.\-]", "", value).replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None

        for full_tag, label in ASSET_TAGS.items():
            short_tag = full_tag.split(":")[-1]
            numbers = []
            for el in root.iter():
                if el.tag.endswith(short_tag):
                    num = to_float(el.text.strip() if el.text else "")
                    if isinstance(num, (float, int)) and num != 0:
                        numbers.append(num)
            if numbers:
                results.append({
                    "tag": full_tag,
                    "label": label,
                    "value": float(max(numbers)),
                })

        ordered = list(ASSET_TAGS.keys())
        results.sort(key=lambda x: ordered.index(x["tag"]) if x["tag"] in ordered else len(ordered))
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
