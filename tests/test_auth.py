from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from ripley_auth import (
    AuthenticatedRipleySession,
    AuthenticationError,
    RipleyCredentials,
    read_secret,
)
from ripley_client import RipleyClient


LOGIN_HTML = """<!doctype html><html><body>
<form method="post" id="gform_0">
  <input name="state_0" value="fresh-state">
  <input name="is_submit_0" value="1">
  <input name="input_1" value="">
  <input name="input_2" type="password" value="">
  <input name="input_3.1" type="checkbox" value="1">
</form></body></html>"""

DASHBOARD_HTML = """<!doctype html><html><body>
<form id="gform_60">
  <select id="input_60_42"><option value="10" selected>Supervisor</option></select>
  <select id="input_60_51"><option value="20" selected>Organization</option></select>
</form></body></html>"""

HOME_HTML = "<!doctype html><html><head><title>Home</title></head><body></body></html>"


class RipleyState:
    username = "person@example.test"
    password = "correct-horse-battery-staple"

    def __init__(self) -> None:
        self.login_attempts = 0
        self.expected_token = "no-valid-session"
        self.expired_redirects_home = False

    def expire(self) -> None:
        self.expected_token = "expired"


@pytest.fixture()
def fake_ripley():
    state = RipleyState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _html(self, body: str, status: int = 200, headers=None):
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            for key, value in headers or []:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path.startswith("/login"):
                self._html(LOGIN_HTML)
                return
            if self.path.startswith("/dashboard"):
                cookie = self.headers.get("Cookie", "")
                if f"ripleysession={state.expected_token}" in cookie:
                    self._html(DASHBOARD_HTML)
                elif state.expired_redirects_home:
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                else:
                    self._html(LOGIN_HTML)
                return
            if self.path == "/":
                self._html(HOME_HTML)
                return
            self._html("not found", status=404)

        def do_POST(self):
            if not self.path.startswith("/login"):
                self._html("not found", status=404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            values = parse_qs(self.rfile.read(length).decode("utf-8"))
            state.login_attempts += 1
            if (
                values.get("input_1") == [state.username]
                and values.get("input_2") == [state.password]
                and values.get("state_0") == ["fresh-state"]
            ):
                token = f"token-{state.login_attempts}"
                state.expected_token = token
                self._html(
                    DASHBOARD_HTML,
                    headers=[("Set-Cookie", f"ripleysession={token}; Path=/; HttpOnly")],
                )
            else:
                self._html(LOGIN_HTML)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def make_client(base_url: str, cookie_path: Path, password: str | None = None):
    credentials = RipleyCredentials(
        RipleyState.username, password if password is not None else RipleyState.password
    )
    auth = AuthenticatedRipleySession(
        credentials,
        base_url=base_url,
        cookie_jar_path=cookie_path,
        timeout=3,
    )
    return RipleyClient(credentials, auth_session=auth)


def test_cold_start_logs_in_and_persists_cookie(fake_ripley, tmp_path):
    state, base_url = fake_ripley
    cookie_path = tmp_path / "state" / "session.cookies"

    result = make_client(base_url, cookie_path).status()

    assert result["authenticated"] is True
    assert result["automatic_reauthentication"] is True
    assert state.login_attempts == 1
    assert cookie_path.exists()
    cookie_text = cookie_path.read_text(encoding="utf-8")
    assert RipleyState.username not in cookie_text
    assert RipleyState.password not in cookie_text


def test_saved_cookie_is_reused_after_client_restart(fake_ripley, tmp_path):
    state, base_url = fake_ripley
    cookie_path = tmp_path / "session.cookies"
    make_client(base_url, cookie_path).status()
    assert state.login_attempts == 1

    make_client(base_url, cookie_path).status()

    assert state.login_attempts == 1


def test_forced_expiry_reauthenticates_and_retries_once(fake_ripley, tmp_path):
    state, base_url = fake_ripley
    client = make_client(base_url, tmp_path / "session.cookies")
    client.status()
    state.expire()

    result = client.status()

    assert result["authenticated"] is True
    assert state.login_attempts == 2


def test_home_redirect_is_treated_as_expired_session(fake_ripley, tmp_path):
    state, base_url = fake_ripley
    client = make_client(base_url, tmp_path / "session.cookies")
    client.status()
    state.expire()
    state.expired_redirects_home = True

    result = client.status()

    assert result["authenticated"] is True
    assert state.login_attempts == 2


def test_bad_credentials_are_not_exposed(fake_ripley, tmp_path):
    _state, base_url = fake_ripley
    bad_password = "never-print-this-value"
    with pytest.raises(AuthenticationError) as caught:
        make_client(base_url, tmp_path / "session.cookies", bad_password).status()
    assert bad_password not in str(caught.value)


def test_secret_file_loading(monkeypatch, tmp_path):
    secret_path = tmp_path / "secret"
    secret_path.write_text("stored-value\n", encoding="utf-8")
    if os.name != "nt":
        secret_path.chmod(0o600)
    monkeypatch.setenv("TEST_SECRET_FILE", str(secret_path))
    monkeypatch.delenv("TEST_SECRET", raising=False)
    assert read_secret("TEST_SECRET", "TEST_SECRET_FILE") == "stored-value"
