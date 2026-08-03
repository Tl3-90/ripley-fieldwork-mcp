from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://digi.hopto.me/ripley-api"
API_KEY_PATH = Path("/opt/ripley-api/secrets/ripley_api_key.txt")


def api_request(
    method: str,
    path: str,
    *,
    api_key: str,
    payload: dict | None = None,
    query: dict[str, str] | None = None,
) -> dict:
    url = BASE_URL + path
    if query:
        url += "?" + urlencode(query)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def selected_id(items: list[dict], label: str) -> str:
    choices = [item for item in items if str(item.get("id", "")).strip()]
    if not choices:
        raise RuntimeError(f"Ripley returned no usable {label} IDs")
    selected = next((item for item in choices if item.get("selected")), choices[0])
    return str(selected["id"])


def find_marker(api_key: str, marker: str) -> tuple[str, str] | None:
    for period in api_request("GET", "/periods", api_key=api_key):
        period_id = str(period["period_id"])
        result = api_request(
            "GET", f"/periods/{period_id}/entries", api_key=api_key
        )
        for entry in result.get("entries", []):
            if marker in str(entry.get("description", "")):
                return period_id, str(entry["hours_id"])
    return None


def ensure_absent(api_key: str, marker: str, hours_id: str | None) -> None:
    found = find_marker(api_key, marker)
    if found is not None or (hours_id and found and found[1] == hours_id):
        raise RuntimeError("Temporary Priority 4 entry still exists after deletion")


def main() -> None:
    api_key = API_KEY_PATH.read_text(encoding="utf-8").strip()
    if not api_key:
        raise SystemExit("API key file is empty")

    metadata = api_request("GET", "/metadata", api_key=api_key)
    supervisor_id = selected_id(metadata.get("supervisors", []), "supervisor")
    organization_id = selected_id(metadata.get("organizations", []), "organization")

    # Indianapolis observes UTC-04:00 on this August 2026 verification date.
    now = datetime.now(timezone(timedelta(hours=-4)))
    marker = f"CODEX-PRIORITY4-{now:%Y%m%d%H%M%S}"
    test_date = (now.date() + timedelta(days=1)).isoformat()
    base_entry = {
        "date": test_date,
        "start_time": "02:17",
        "end_time": "02:32",
        "supervisor_id": supervisor_id,
        "organization_id": organization_id,
        "hour_type": "Independent",
        "independent_restricted": 0,
        "independent_unrestricted": 0.25,
        "supervised_individual_restricted": 0,
        "supervised_individual_unrestricted": 0,
        "supervised_group_unrestricted": 0,
        "observation_time": 0,
        "description": marker,
    }
    batch = {
        "entries": [base_entry],
        "dry_run": True,
        "stop_on_error": True,
        "allow_duplicates": False,
    }

    period_id: str | None = None
    hours_id: str | None = None
    created = False
    try:
        dry_run = api_request("POST", "/entries/bulk", api_key=api_key, payload=batch)
        if not dry_run.get("ok") or dry_run.get("processed") != 1:
            raise RuntimeError(f"Bulk dry run failed: {dry_run}")
        print("1 DRY_RUN_OK")

        batch["dry_run"] = False
        live_create = api_request(
            "POST", "/entries/bulk", api_key=api_key, payload=batch
        )
        if not live_create.get("ok") or live_create.get("succeeded") != 1:
            raise RuntimeError(f"Live bulk create failed: {live_create}")
        created = True
        print("2 PUBLIC_BATCH_CREATE_OK")

        found = find_marker(api_key, marker)
        if found is None:
            raise RuntimeError("Created Priority 4 entry could not be read back")
        period_id, hours_id = found
        print(f"3 CREATE_READBACK_OK period_id={period_id} hours_id={hours_id}")

        edited_entry = {**base_entry, "description": marker + "-EDITED"}
        update = api_request(
            "PUT",
            f"/entries/{hours_id}",
            api_key=api_key,
            payload=edited_entry,
            query={"dry_run": "false"},
        )
        if not update.get("ok") or update.get("dry_run"):
            raise RuntimeError(f"Live edit failed: {update}")
        edited = find_marker(api_key, marker + "-EDITED")
        if edited != (period_id, hours_id):
            raise RuntimeError("Edited Priority 4 entry could not be verified")
        print("4 PUBLIC_EDIT_AND_READBACK_OK")

        deleted = api_request(
            "DELETE",
            f"/entries/{hours_id}",
            api_key=api_key,
            query={"period_id": period_id, "confirm": "true"},
        )
        if not deleted.get("ok") or deleted.get("dry_run"):
            raise RuntimeError(f"Live delete failed: {deleted}")
        created = False
        ensure_absent(api_key, marker, hours_id)
        print("5 PUBLIC_DELETE_AND_ABSENCE_OK")
        print("PRIORITY4_COMPLETE_NO_TEST_RECORD_REMAINS")
    finally:
        if created:
            if period_id is None or hours_id is None:
                found = find_marker(api_key, marker)
                if found is not None:
                    period_id, hours_id = found
            if period_id and hours_id:
                try:
                    api_request(
                        "DELETE",
                        f"/entries/{hours_id}",
                        api_key=api_key,
                        query={"period_id": period_id, "confirm": "true"},
                    )
                    ensure_absent(api_key, marker, hours_id)
                    print("CLEANUP_OK")
                except Exception as cleanup_error:
                    print(f"CLEANUP_FAILED: {cleanup_error}", file=sys.stderr)


if __name__ == "__main__":
    main()
