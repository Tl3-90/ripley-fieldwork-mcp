from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import Client


MCP_URL = os.getenv(
    "RIPLEY_MCP_URL", "https://digi.hopto.me/ripley-api/mcp"
)
API_KEY_PATH = Path(
    os.getenv("RIPLEY_API_KEY_PATH", "/run/secrets/ripley_api_key")
)

EXPECTED_TOOLS = {
    "ripley_check_health",
    "ripley_get_metadata",
    "ripley_list_periods",
    "ripley_list_entries",
    "ripley_validate_entry",
    "ripley_validate_batch",
    "ripley_create_entry",
    "ripley_bulk_create_entries",
    "ripley_update_entry",
    "ripley_delete_entry",
}


def selected_id(items: list[dict], label: str) -> str:
    choices = [item for item in items if str(item.get("id", "")).strip()]
    if not choices:
        raise RuntimeError(f"Ripley returned no usable {label} IDs")
    selected = next((item for item in choices if item.get("selected")), choices[0])
    return str(selected["id"])


async def result_data(client: Client, tool: str, arguments: dict | None = None) -> dict:
    result = await client.call_tool(tool, arguments or {})
    if result.is_error or not isinstance(result.data, dict):
        raise RuntimeError(f"{tool} failed: {result}")
    return result.data


async def find_marker(client: Client, marker: str) -> tuple[str, str] | None:
    periods = await result_data(client, "ripley_list_periods")
    for period in periods.get("periods", []):
        period_id = str(period["period_id"])
        result = await result_data(
            client, "ripley_list_entries", {"period_id": period_id}
        )
        for entry in result.get("entries", []):
            if marker in str(entry.get("description", "")):
                return period_id, str(entry["hours_id"])
    return None


async def main() -> None:
    api_key = API_KEY_PATH.read_text(encoding="utf-8").strip()
    if not api_key:
        raise RuntimeError("MCP API key file is empty")

    # Indianapolis is UTC-04:00 on the August 2026 verification date.
    now = datetime.now(timezone(timedelta(hours=-4)))
    marker = f"CODEX-MCP-{now:%Y%m%d%H%M%S}"
    entry = {
        "date": (now.date() + timedelta(days=2)).isoformat(),
        "start_time": "03:17",
        "end_time": "03:32",
        "supervisor_id": "",
        "organization_id": "",
        "hour_type": "Independent",
        "independent_restricted": 0,
        "independent_unrestricted": 0.25,
        "supervised_individual_restricted": 0,
        "supervised_individual_unrestricted": 0,
        "supervised_group_unrestricted": 0,
        "observation_time": 0,
        "description": marker,
    }

    created = False
    period_id: str | None = None
    hours_id: str | None = None
    async with Client(MCP_URL, auth=api_key) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        if names != EXPECTED_TOOLS:
            raise RuntimeError(f"Unexpected MCP tool set: {sorted(names)}")
        print("1 MCP_DISCOVERY_OK tools=10")

        health = await result_data(client, "ripley_check_health")
        if not health.get("authenticated"):
            raise RuntimeError("MCP account health is not authenticated")
        print("2 MCP_AUTHENTICATED_HEALTH_OK")

        metadata = await result_data(client, "ripley_get_metadata")
        entry["supervisor_id"] = selected_id(metadata.get("supervisors", []), "supervisor")
        entry["organization_id"] = selected_id(
            metadata.get("organizations", []), "organization"
        )
        validation = await result_data(
            client, "ripley_validate_entry", {"entry": entry}
        )
        if not validation.get("ok") or not validation.get("dry_run"):
            raise RuntimeError(f"MCP validation failed: {validation}")
        print("3 MCP_VALIDATE_OK")

        try:
            creation = await result_data(
                client,
                "ripley_create_entry",
                {"entry": entry, "confirm": True},
            )
            if not creation.get("ok") or creation.get("dry_run"):
                raise RuntimeError(f"MCP create failed: {creation}")
            created = True
            found = await find_marker(client, marker)
            if found is None:
                raise RuntimeError("MCP-created entry could not be read back")
            period_id, hours_id = found
            print(f"4 MCP_CREATE_READBACK_OK period_id={period_id} hours_id={hours_id}")

            edited = {**entry, "description": marker + "-EDITED"}
            update = await result_data(
                client,
                "ripley_update_entry",
                {"hours_id": hours_id, "entry": edited, "confirm": True},
            )
            if not update.get("ok") or update.get("dry_run"):
                raise RuntimeError(f"MCP update failed: {update}")
            if await find_marker(client, marker + "-EDITED") != (period_id, hours_id):
                raise RuntimeError("MCP-edited entry could not be read back")
            print("5 MCP_UPDATE_READBACK_OK")

            deleted = await result_data(
                client,
                "ripley_delete_entry",
                {
                    "hours_id": hours_id,
                    "period_id": period_id,
                    "confirm": True,
                },
            )
            if not deleted.get("ok") or deleted.get("dry_run"):
                raise RuntimeError(f"MCP delete failed: {deleted}")
            created = False
            if await find_marker(client, marker) is not None:
                raise RuntimeError("Temporary MCP entry remains after deletion")
            print("6 MCP_DELETE_ABSENCE_OK")
            print("PUBLIC_MCP_COMPLETE_NO_TEST_RECORD_REMAINS")
        finally:
            if created:
                if period_id is None or hours_id is None:
                    found = await find_marker(client, marker)
                    if found is not None:
                        period_id, hours_id = found
                if period_id and hours_id:
                    await result_data(
                        client,
                        "ripley_delete_entry",
                        {
                            "hours_id": hours_id,
                            "period_id": period_id,
                            "confirm": True,
                        },
                    )
                    if await find_marker(client, marker) is not None:
                        raise RuntimeError("MCP cleanup could not remove test entry")
                    print("MCP_CLEANUP_OK")


if __name__ == "__main__":
    asyncio.run(main())
