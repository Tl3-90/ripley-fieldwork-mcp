from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path


PROJECT_DIR = Path("/opt/ripley-api")
SECRET_DIR = PROJECT_DIR / "secrets"
STATE_DIR = PROJECT_DIR / "state"
APP_UID = 10001
APP_GID = 10001


def atomic_secret(path: Path, value: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=SECRET_DIR)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary_path, APP_UID, APP_GID)
        os.chmod(temporary_path, 0o400)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    encoded = sys.stdin.buffer.readline().strip()
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True))
        username = str(payload["username"]).strip()
        password = str(payload["password"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit("Invalid credential payload") from exc
    if not username or not password:
        raise SystemExit("Username and password are required")

    SECRET_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(SECRET_DIR, 0, 0)
    os.chmod(SECRET_DIR, 0o700)
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(STATE_DIR, APP_UID, APP_GID)
    os.chmod(STATE_DIR, 0o700)

    atomic_secret(SECRET_DIR / "ripley_username.txt", username)
    atomic_secret(SECRET_DIR / "ripley_password.txt", password)
    api_key_path = SECRET_DIR / "ripley_api_key.txt"
    if not api_key_path.exists() or not api_key_path.stat().st_size:
        atomic_secret(api_key_path, secrets.token_hex(32))
    else:
        os.chown(api_key_path, APP_UID, APP_GID)
        os.chmod(api_key_path, 0o400)
    print("RIPLEY_SECRETS_STORED")


if __name__ == "__main__":
    main()
