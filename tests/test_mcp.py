import asyncio
import os

os.environ.setdefault("RIPLEY_API_KEY", "test-key")
os.environ.setdefault("RIPLEY_COOKIE", "wordpress_logged_in=fake")

from fastapi.testclient import TestClient
from fastmcp import Client

import app as api_module


ENTRY = {
    "date": "2026-08-03",
    "start_time": "09:00",
    "end_time": "11:00",
    "supervisor_id": "10",
    "organization_id": "20",
    "hour_type": "Independent",
    "independent_unrestricted": 2,
    "description": "MCP integration test",
}


class FakeRipleyClient:
    def status(self):
        return {"authenticated": True, "automatic_reauthentication": True}

    def metadata(self):
        return {
            "supervisors": [{"id": "10", "name": "Supervisor"}],
            "organizations": [{"id": "20", "name": "Organization"}],
        }

    def list_periods(self):
        return [{"period_id": "30", "label": "August 2026"}]

    def list_entries(self, period_id):
        return {"period_id": period_id, "count": 0, "entries": []}

    def create_entry(self, entry, dry_run=True):
        return {"ok": True, "dry_run": dry_run, "operation": "create"}

    def update_entry(self, hours_id, entry, dry_run=True):
        return {
            "ok": True,
            "dry_run": dry_run,
            "operation": "update",
            "hours_id": hours_id,
        }

    def delete_entry(self, hours_id, period_id, confirm=False):
        return {
            "ok": True,
            "dry_run": not confirm,
            "operation": "delete",
            "hours_id": hours_id,
            "period_id": period_id,
        }


def run(coroutine):
    return asyncio.run(coroutine)


async def list_tools():
    async with Client(api_module.mcp) as client:
        return await client.list_tools()


async def call_tool(name, arguments, *, raise_on_error=True):
    async with Client(api_module.mcp) as client:
        return await client.call_tool(
            name,
            arguments,
            raise_on_error=raise_on_error,
        )


def test_mcp_exposes_expected_tools_and_safety_annotations():
    tools = {tool.name: tool for tool in run(list_tools())}
    assert set(tools) == {
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
    assert tools["ripley_get_metadata"].annotations.readOnlyHint is True
    assert tools["ripley_create_entry"].annotations.readOnlyHint is False
    assert tools["ripley_delete_entry"].annotations.destructiveHint is True


def test_mcp_reads_validate_and_confirmed_writes(monkeypatch):
    monkeypatch.setattr(api_module, "get_client", lambda: FakeRipleyClient())

    metadata = run(call_tool("ripley_get_metadata", {}))
    assert metadata.data["supervisors"][0]["id"] == "10"

    validation = run(call_tool("ripley_validate_entry", {"entry": ENTRY}))
    assert validation.data == {"ok": True, "dry_run": True, "operation": "create"}

    rejected = run(
        call_tool(
            "ripley_create_entry",
            {"entry": ENTRY, "confirm": False},
            raise_on_error=False,
        )
    )
    assert rejected.is_error is True

    created = run(
        call_tool("ripley_create_entry", {"entry": ENTRY, "confirm": True})
    )
    assert created.data == {"ok": True, "dry_run": False, "operation": "create"}

    deleted = run(
        call_tool(
            "ripley_delete_entry",
            {"hours_id": "40", "period_id": "30", "confirm": True},
        )
    )
    assert deleted.data["dry_run"] is False


def test_remote_mcp_requires_bearer_token_and_checks_origin(monkeypatch):
    monkeypatch.setenv("RIPLEY_API_KEY", "test-key")
    monkeypatch.delenv("RIPLEY_API_KEY_FILE", raising=False)

    with TestClient(api_module.app) as client:
        missing = client.post("/mcp/")
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"

        wrong = client.post(
            "/mcp/",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert wrong.status_code == 401

        bad_origin = client.post(
            "/mcp/",
            headers={
                "Authorization": "Bearer test-key",
                "Origin": "https://example.invalid",
            },
        )
        assert bad_origin.status_code == 403

        authenticated = client.post(
            "/mcp/",
            headers={"Authorization": "Bearer test-key"},
        )
        assert authenticated.status_code != 401
