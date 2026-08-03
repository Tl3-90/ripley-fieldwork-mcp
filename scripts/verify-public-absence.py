from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://digi.hopto.me/ripley-api"
API_KEY_PATH = Path("/opt/ripley-api/secrets/ripley_api_key.txt")


def get_json(path: str, api_key: str) -> object:
    request = Request(
        BASE_URL + path,
        headers={"X-API-Key": api_key, "Accept": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify-public-absence.py PERIOD_ID HOURS_ID")
    period_id, hours_id = sys.argv[1:]
    api_key = API_KEY_PATH.read_text(encoding="utf-8").strip()

    periods = get_json("/periods", api_key)
    period_ids = {str(item["period_id"]) for item in periods}
    if period_id not in period_ids:
        print("INDEPENDENT_ABSENCE_OK_EMPTY_PERIOD_REMOVED")
    else:
        result = get_json(f"/periods/{period_id}/entries", api_key)
        hours_ids = {str(item["hours_id"]) for item in result.get("entries", [])}
        if hours_id in hours_ids:
            raise SystemExit("Temporary Priority 4 entry still exists")
        print("INDEPENDENT_ABSENCE_OK_ENTRY_NOT_IN_PERIOD")

    health = get_json("/health", api_key)
    if not health.get("authenticated"):
        raise SystemExit("Public API health is not authenticated")
    print("PUBLIC_HEALTH_OK")


if __name__ == "__main__":
    main()
