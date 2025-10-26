from fastapi import FastAPI, Query
from fetch import Fetch

app = FastAPI(title="CVR Service")

# Create a single Fetch instance (reuse session across requests)
fetch = Fetch()

@app.get("/health")
def health():
    return {"status": "ok"}



@app.get("/search")
def search(name: str = Query(..., description="Company name to search for")):
    cvr, cname = fetch.search_company(name)
    if not cvr:
        return {"query": name, "error": "No company under konkurs found"}
    return {"query": name, "cvr": cvr, "name": cname}


@app.get("/company/{cvr}")
def company(cvr: str):
    data = fetch.fetch_company_data(cvr)
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


@app.get("/assets/{name}")
def assets(name: str):
    cvr, cname = fetch.search_company(name)
    if not cvr:
        return {"query": name, "error": "No company under konkurs found"}
    data = fetch.fetch_company_data(cvr)
    urls = fetch.find_latest_xbrl(data, cvr)
    if not urls or not urls[0]:
        return {"cvr": cvr, "error": "No XBRL document found"}
    xml_bytes = fetch.download_xbrl(urls[0], urls[1])
    assets = fetch.parse_xbrl_assets(xml_bytes)
    formatted = [{"tag": t, "label": l, "value": v} for t, l, v in assets]
    return {"cvr": cvr, "assets": formatted}
