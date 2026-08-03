from __future__ import annotations

import shutil
from pathlib import Path

from bs4 import BeautifulSoup

from ripley_auth import AuthenticatedRipleySession, load_credentials


source = Path("/var/lib/ripley-api/session.cookies")
test_jar = Path("/var/lib/ripley-api/.forced-expiry-test.cookies")

if not source.exists():
    raise SystemExit("Live session cookie jar is missing")

shutil.copy2(source, test_jar)
try:
    auth = AuthenticatedRipleySession(load_credentials(), cookie_jar_path=test_jar)
    for cookie in auth.session.cookies:
        cookie.value = "forced-expired-session"
    response = auth.request("GET", "/dashboard/")
    if BeautifulSoup(response.text, "html.parser").select_one("#gform_60") is None:
        raise SystemExit("Automatic session renewal did not restore the dashboard")
    print("FORCED_EXPIRY_REAUTH_OK")
finally:
    test_jar.unlink(missing_ok=True)
