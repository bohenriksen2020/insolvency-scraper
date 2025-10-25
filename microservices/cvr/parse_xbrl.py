from __future__ import annotations

from io import BytesIO
from typing import List, Tuple
import xml.etree.ElementTree as ET

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


def parse_xbrl_assets(xml_content: bytes) -> List[Tuple[str, str, float]]:
    """Extract tangible asset fields from XBRL XML."""
    tree = ET.parse(BytesIO(xml_content))
    root = tree.getroot()

    results: List[Tuple[str, str, float]] = []

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
