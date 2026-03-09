"""Safety API router — NHTSA for vehicles, CPSC for consumer products."""

import requests


# ---------------------------------------------------------------------------
# NHTSA (vehicles)
# ---------------------------------------------------------------------------

RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
VIN_DECODE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin"


def check_vehicle_recalls(make: str, model: str, year: int) -> dict:
    """Check for open safety recalls via NHTSA API.

    Returns dict with keys: count (int), recalls (list[dict]), error (str|None).
    Each recall dict has: component, summary, remedy, nhtsa_id.
    """
    try:
        resp = requests.get(
            RECALLS_URL,
            params={"make": make, "model": model, "modelYear": str(year)},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        recalls = []
        for r in results:
            recalls.append({
                "component": r.get("Component", "Unknown"),
                "summary": r.get("Summary", ""),
                "remedy": r.get("Remedy", ""),
                "nhtsa_id": r.get("NHTSACampaignNumber", ""),
            })

        return {"count": len(recalls), "recalls": recalls, "error": None}
    except Exception as e:
        return {"count": 0, "recalls": [], "error": str(e)}


def decode_vin(vin: str) -> dict:
    """Decode a VIN via NHTSA vPIC API.

    Returns dict with keys: year, make, model, trim, body_class, engine, error.
    """
    try:
        resp = requests.get(
            f"{VIN_DECODE_URL}/{vin}",
            params={"format": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = {
            r["Variable"]: r["Value"]
            for r in data.get("Results", [])
            if r.get("Value")
        }

        year_str = results.get("Model Year", "")
        cylinders = results.get("Engine Number of Cylinders", "")
        displacement = results.get("Displacement (L)", "")
        engine = ""
        if cylinders or displacement:
            parts = []
            if cylinders:
                parts.append(f"{cylinders}-cyl")
            if displacement:
                parts.append(f"{displacement}L")
            engine = " ".join(parts)

        return {
            "year": int(year_str) if year_str and year_str.isdigit() else None,
            "make": results.get("Make", ""),
            "model": results.get("Model", ""),
            "trim": results.get("Trim", ""),
            "body_class": results.get("Body Class", ""),
            "engine": engine,
            "error": None,
        }
    except Exception as e:
        return {
            "year": None, "make": "", "model": "", "trim": "",
            "body_class": "", "engine": "", "error": str(e),
        }


# ---------------------------------------------------------------------------
# CPSC (consumer products — furniture, electronics, etc.)
# ---------------------------------------------------------------------------

CPSC_URL = "https://www.saferproducts.gov/api/Query"


def check_cpsc_recalls(product_name: str, max_results: int = 10) -> dict:
    """Check CPSC SaferProducts.gov for product recalls.

    Returns dict with keys: count (int), recalls (list[dict]), error (str|None).
    Each recall dict has: title, description, url, date.
    """
    try:
        params = {
            "format": "json",
            "ProductName": product_name,
            "RecallDateStart": "2015-01-01",
        }
        resp = requests.get(CPSC_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recalls = []
        for item in data[:max_results]:
            recalls.append({
                "title": item.get("Title", ""),
                "description": item.get("Description", ""),
                "url": item.get("URL", ""),
                "date": item.get("RecallDate", ""),
            })

        return {"count": len(recalls), "recalls": recalls, "error": None}
    except Exception as e:
        return {"count": 0, "recalls": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def check_safety(
    safety_api: str | None,
    item_fields: dict,
    item_name: str = "",
) -> str:
    """Route to the appropriate safety API based on item type config.

    Returns a formatted string of safety findings, or empty string if none.
    """
    if not safety_api:
        return ""

    if safety_api == "nhtsa":
        make = item_fields.get("make", "")
        model = item_fields.get("model", "")
        year = item_fields.get("year")
        if not (make and model and year):
            return ""

        try:
            year_int = int(year)
        except (TypeError, ValueError):
            return ""

        if year_int < 1966:
            print(f"  Skipping NHTSA — not available for pre-1966 vehicles ({year})")
            return ""

        print(f"  Checking NHTSA recalls for {year} {make} {model}...")
        result = check_vehicle_recalls(str(make), str(model), year_int)
        if result["count"] > 0:
            print(f"  Found {result['count']} recall(s)")
            lines = [f"NHTSA SAFETY RECALLS ({result['count']} found):"]
            for r in result["recalls"][:10]:
                lines.append(
                    f"- [{r['nhtsa_id']}] {r['component']}: "
                    f"{r['summary'][:200]}"
                )
                if r["remedy"]:
                    lines.append(f"  Remedy: {r['remedy'][:200]}")
            return "\n".join(lines)
        elif result["error"]:
            print(f"  NHTSA API error: {result['error']}")
        else:
            print("  No open recalls found")
        return ""

    if safety_api == "cpsc":
        if not item_name:
            return ""

        print(f"  Checking CPSC recalls for {item_name}...")
        result = check_cpsc_recalls(item_name)
        if result["count"] > 0:
            print(f"  Found {result['count']} recall(s)")
            lines = [f"CPSC PRODUCT RECALLS ({result['count']} found):"]
            for r in result["recalls"][:5]:
                lines.append(f"- {r['title']}: {r['description'][:200]}")
                if r["url"]:
                    lines.append(f"  Details: {r['url']}")
            return "\n".join(lines)
        elif result["error"]:
            print(f"  CPSC API error: {result['error']}")
        else:
            print("  No product recalls found")
        return ""

    print(f"  Unknown safety API: {safety_api}")
    return ""
