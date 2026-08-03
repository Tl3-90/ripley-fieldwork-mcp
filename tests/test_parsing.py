from types import SimpleNamespace

from ripley_auth import RipleyCredentials
from ripley_client import RipleyClient


DASHBOARD = """
<html><body>
  <form id="gform_60">
    <select id="input_60_42"><option value="10" selected>Supervisor One</option></select>
    <select id="input_60_51"><option value="20" selected>Organization One</option></select>
  </form>
  <a href="/dashboard/period/?period_id=30">August 2026 Organization One</a>
</body></html>
"""


PERIOD = """
<html><body><table>
  <tr><th>Date</th><th>Start Time</th><th>End Time</th><th>Supervisor</th>
      <th>Restricted</th><th>Unrestricted</th><th>Restricted</th><th>Unrestricted</th>
      <th>Group</th><th>Contact Type</th><th>Format</th></tr>
  <tr><td>August 3, 2026</td><td>9:00 AM</td><td>11:00 AM</td><td>S. ONE</td>
      <td>0</td><td>2</td><td>0</td><td>0</td><td>0</td><td></td><td></td>
      <td><a class="editHours" hours_id="40" href="#"></a></td></tr>
  <tr><td>Prepared training materials.</td></tr>
</table></body></html>
"""


def fake_response(text, url):
    return SimpleNamespace(text=text, url=url)


def test_dashboard_and_period_parsing(monkeypatch):
    client = RipleyClient(RipleyCredentials("test@example.test", "test-password"))

    def fake_get(path):
        if "period" in path:
            return fake_response(PERIOD, "https://ripleyfieldworktracker.com/dashboard/period/?period_id=30")
        return fake_response(DASHBOARD, "https://ripleyfieldworktracker.com/dashboard/")

    monkeypatch.setattr(client, "_get", fake_get)

    metadata = client.metadata()
    assert metadata["supervisors"][0]["id"] == "10"
    assert metadata["organizations"][0]["id"] == "20"
    assert client.list_periods()[0]["period_id"] == "30"

    parsed = client.list_entries("30")
    assert parsed["count"] == 1
    assert parsed["entries"][0]["hours_id"] == "40"
    assert parsed["entries"][0]["independent_unrestricted"] == 2
    assert parsed["entries"][0]["description"] == "Prepared training materials."
