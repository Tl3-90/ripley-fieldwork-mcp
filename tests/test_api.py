import os

os.environ.setdefault("RIPLEY_API_KEY", "test-key")
os.environ.setdefault("RIPLEY_COOKIE", "wordpress_logged_in=fake")

from fastapi.testclient import TestClient

import app as api_module


class FakeRipleyClient:
    def status(self):
        return {"authenticated": True, "form_60_available": True}

    def metadata(self):
        return {
            "supervisors": [{"id": "10", "name": "Supervisor", "selected": True}],
            "organizations": [{"id": "20", "name": "Organization", "selected": True}],
        }

    def list_periods(self):
        return [{"period_id": "30", "label": "August 2026"}]

    def list_entries(self, period_id):
        return {"period_id": period_id, "count": 0, "entries": []}

    def create_entry(self, entry, dry_run=True):
        return {"ok": True, "dry_run": dry_run, "operation": "create"}

    def update_entry(self, hours_id, entry, dry_run=True):
        return {"ok": True, "dry_run": dry_run, "operation": "update", "hours_id": hours_id}

    def delete_entry(self, hours_id, period_id, confirm=False):
        return {
            "ok": True,
            "dry_run": not confirm,
            "operation": "delete",
            "hours_id": hours_id,
            "period_id": period_id,
        }


api_module.get_client = lambda: FakeRipleyClient()
client = TestClient(api_module.app)
headers = {"X-API-Key": "test-key"}


ENTRY = {
    "date": "2026-08-03",
    "start_time": "09:00",
    "end_time": "11:00",
    "supervisor_id": "10",
    "organization_id": "20",
    "hour_type": "Independent",
    "independent_unrestricted": 2,
    "description": "Integration test",
}


def test_api_key_is_required():
    response = client.get("/health")
    assert response.status_code == 401


def test_wrong_api_key_is_rejected():
    response = client.get("/health", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_api_key_can_be_loaded_from_secret_file(tmp_path, monkeypatch):
    secret_path = tmp_path / "api-key"
    secret_path.write_text("file-secret-key\n", encoding="utf-8")
    monkeypatch.setenv("RIPLEY_API_KEY_FILE", str(secret_path))

    assert client.get("/health", headers={"X-API-Key": "file-secret-key"}).status_code == 200
    assert client.get("/health", headers=headers).status_code == 401


def test_container_health_does_not_require_account_access():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_read_endpoints():
    assert client.get("/health", headers=headers).status_code == 200
    assert client.get("/metadata", headers=headers).status_code == 200
    assert client.get("/periods", headers=headers).status_code == 200
    response = client.get("/periods/30/entries", headers=headers)
    assert response.status_code == 200
    assert response.json()["period_id"] == "30"


def test_write_endpoints_default_safe():
    created = client.post("/entries", headers=headers, json=ENTRY)
    assert created.status_code == 200
    assert created.json()["dry_run"] is True

    updated = client.put("/entries/40", headers=headers, json=ENTRY)
    assert updated.status_code == 200
    assert updated.json()["dry_run"] is True

    deleted = client.delete("/entries/40?period_id=30", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["dry_run"] is True


def test_bulk_json_and_csv():
    bulk = client.post(
        "/entries/bulk",
        headers=headers,
        json={"entries": [ENTRY], "dry_run": True},
    )
    assert bulk.status_code == 200
    assert bulk.json()["processed"] == 1

    csv_body = (
        "date,start_time,end_time,supervisor_id,organization_id,hour_type,"
        "independent_unrestricted,description\n"
        "2026-08-03,09:00,11:00,10,20,Independent,2,CSV integration test\n"
    )
    csv_response = client.post(
        "/entries/bulk/csv?dry_run=true",
        headers={**headers, "Content-Type": "text/csv"},
        content=csv_body,
    )
    assert csv_response.status_code == 200
    assert csv_response.json()["processed"] == 1
