from __future__ import annotations

import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


class AuthenticationError(RuntimeError):
    """Raised when Ripley credentials or the authenticated session are unusable."""


@dataclass(frozen=True)
class RipleyCredentials:
    username: str
    password: str


def read_secret(
    value_name: str,
    file_name: str,
    *,
    default_file: str | None = None,
) -> str:
    """Read a secret from a restricted file, with an environment fallback for tests."""
    configured_path = os.getenv(file_name, default_file or "").strip()
    if configured_path:
        path = Path(configured_path)
        if path.exists():
            _assert_restricted_file(path)
            value = path.read_text(encoding="utf-8").strip()
            if not value:
                raise AuthenticationError(f"{file_name} points to an empty secret file")
            return value

    value = os.getenv(value_name, "").strip()
    if value:
        return value
    raise AuthenticationError(f"Configure {file_name} with a restricted secret file")


def _assert_restricted_file(path: Path) -> None:
    if not path.is_file():
        raise AuthenticationError("Configured secret path is not a regular file")
    if os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise AuthenticationError("Configured secret file must use mode 600 or stricter")


def load_credentials() -> RipleyCredentials:
    return RipleyCredentials(
        username=read_secret(
            "RIPLEY_USERNAME",
            "RIPLEY_USERNAME_FILE",
            default_file="/etc/ripley-api/secrets/username",
        ),
        password=read_secret(
            "RIPLEY_PASSWORD",
            "RIPLEY_PASSWORD_FILE",
            default_file="/etc/ripley-api/secrets/password",
        ),
    )


class AuthenticatedRipleySession:
    """Requests session that logs in, persists cookies, and retries once after expiry."""

    def __init__(
        self,
        credentials: RipleyCredentials,
        *,
        base_url: str = "https://ripleyfieldworktracker.com",
        cookie_jar_path: str | Path = "/var/lib/ripley-api/session.cookies",
        timeout: float = 30,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.cookie_jar_path = Path(cookie_jar_path)
        self.timeout = timeout
        self._auth_lock = threading.Lock()
        self._generation = 0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/150 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._load_cookie_jar()

    def url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Send a request and transparently reauthenticate/retry exactly once."""
        target = path if urlparse(path).scheme else self.url(path)
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("allow_redirects", True)
        observed_generation = self._generation
        response = self.session.request(method, target, **kwargs)
        if self._is_auth_failure(response, requested_url=target):
            self._reauthenticate(observed_generation)
            response = self.session.request(method, target, **kwargs)
            if self._is_auth_failure(response, requested_url=target):
                raise AuthenticationError("Ripley authentication failed after one automatic retry")
        response.raise_for_status()
        self._save_cookie_jar()
        return response

    def login(self) -> None:
        with self._auth_lock:
            self._login_locked()

    def _reauthenticate(self, observed_generation: int) -> None:
        with self._auth_lock:
            if self._generation != observed_generation:
                return
            self._login_locked()

    def _login_locked(self) -> None:
        login_page = self.session.get(
            self.url("/login/"), timeout=self.timeout, allow_redirects=True
        )
        login_page.raise_for_status()
        soup = BeautifulSoup(login_page.text, "html.parser")
        form = soup.select_one("#gform_0")
        if form is None:
            raise AuthenticationError("Ripley login form was not found")

        pairs = self._form_pairs(form)
        override_names = {"input_1", "input_2", "input_3.1", "login_redirect"}
        pairs = [(name, value) for name, value in pairs if name not in override_names]
        pairs.extend(
            [
                ("input_1", self.credentials.username),
                ("input_2", self.credentials.password),
                ("input_3.1", "1"),
                ("login_redirect", "/dashboard/"),
            ]
        )
        action = form.get("action") or login_page.url
        response = self.session.post(
            urljoin(login_page.url, action),
            data=pairs,
            headers={"Referer": login_page.url, "Origin": self.base_url},
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        dashboard = self.session.get(
            self.url("/dashboard/"), timeout=self.timeout, allow_redirects=True
        )
        dashboard.raise_for_status()
        if self._is_auth_failure(
            dashboard, requested_url=self.url("/dashboard/")
        ) or BeautifulSoup(
            dashboard.text, "html.parser"
        ).select_one("#gform_60") is None:
            raise AuthenticationError("Ripley rejected the stored credentials")

        self._generation += 1
        self._save_cookie_jar()

    @staticmethod
    def _is_auth_failure(
        response: requests.Response, requested_url: str | None = None
    ) -> bool:
        path = urlparse(response.url).path.lower()
        if "/login" in path or "/wp-login.php" in path:
            return True
        if requested_url:
            requested_path = urlparse(requested_url).path.lower()
            protected = requested_path.startswith("/dashboard") or requested_path.startswith(
                "/delete-hours"
            )
            if protected and path in {"", "/"}:
                return True
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and "<html" not in response.text[:500].lower():
            return False
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.select_one("#gform_0") is not None or soup.select_one("#user_login") is not None

    @staticmethod
    def _form_pairs(form: Tag) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for element in form.select("input[name], select[name], textarea[name]"):
            if element.has_attr("disabled"):
                continue
            name = element.get("name")
            if not name:
                continue
            kind = (element.get("type") or "").lower()
            if kind in {"submit", "button", "file", "reset"}:
                continue
            if kind in {"checkbox", "radio"} and not element.has_attr("checked"):
                continue
            if element.name == "select":
                selected = element.select("option[selected]") or element.select("option")[:1]
                for option in selected:
                    pairs.append((name, option.get("value", option.get_text())))
            elif element.name == "textarea":
                pairs.append((name, element.get_text()))
            else:
                pairs.append((name, element.get("value", "")))
        return pairs

    def _load_cookie_jar(self) -> None:
        if not self.cookie_jar_path.exists():
            return
        if os.name != "nt" and stat.S_IMODE(self.cookie_jar_path.stat().st_mode) & 0o077:
            raise AuthenticationError("Session cookie file must use mode 600 or stricter")
        jar = MozillaCookieJar(str(self.cookie_jar_path))
        try:
            jar.load(ignore_discard=True, ignore_expires=False)
        except (OSError, ValueError):
            return
        self.session.cookies.update(jar)

    def _save_cookie_jar(self) -> None:
        parent = self.cookie_jar_path.parent
        parent_was_missing = not parent.exists()
        parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt" and parent_was_missing:
            parent.chmod(0o700)
        fd, temp_name = tempfile.mkstemp(prefix=".session-", dir=parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            jar = MozillaCookieJar(str(temp_path))
            for cookie in self.session.cookies:
                jar.set_cookie(cookie)
            jar.save(ignore_discard=True, ignore_expires=True)
            if os.name != "nt":
                temp_path.chmod(0o600)
            os.replace(temp_path, self.cookie_jar_path)
            if os.name != "nt":
                self.cookie_jar_path.chmod(0o600)
        finally:
            if temp_path.exists():
                temp_path.unlink()
