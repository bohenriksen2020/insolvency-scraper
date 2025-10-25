from fastapi import FastAPI, Query
from fetch import (
    search_company,
    fetch_company_data,
    find_latest_xbrl,
    download_xbrl,
    parse_xbrl_assets,
)

app = FastAPI(title="CVR Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search")
def search(name: str = Query(..., description="Company name to search for")):
    cvr, cname = search_company(name)
    if not cvr:
        return {"query": name, "error": "No company under konkurs found"}
    return {"query": name, "cvr": cvr, "name": cname}


@app.get("/company/{cvr}")
def company(cvr: str):
    data = fetch_company_data(cvr)
    meta = data.get("virksomhedMetadata", {})
    addr = data.get("beliggenhedsadresse", {})
    return {
        "cvr": cvr,
        "name": meta.get("navn"),
        "status": meta.get("status"),
        "address": {
            "vejnavn": addr.get("vejnavn"),
            "postnummer": addr.get("postnummer"),
            "by": addr.get("postBy"),
        },
    }


@app.get("/assets/{cvr}")
def assets(cvr: str):
    data = fetch_company_data(cvr)
    urls = find_latest_xbrl(data, cvr)
    if not urls or not urls[0]:
        return {"cvr": cvr, "error": "No XBRL document found"}
    xml_bytes = download_xbrl(urls[0], urls[1])
    assets = parse_xbrl_assets(xml_bytes)
    formatted = [{"tag": t, "label": l, "value": v} for t, l, v in assets]
    return {"cvr": cvr, "assets": formatted}
