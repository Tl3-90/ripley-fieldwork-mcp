# Ripley API and MCP Project Handoff

Date: August 3, 2026

## Hosted MCP completion

The existing Docker service now exposes both interfaces from the same process:

- REST API: `https://digi.hopto.me/ripley-api`
- Remote MCP: `https://digi.hopto.me/ripley-api/mcp`
- MCP transport: Streamable HTTP
- MCP authentication: `Authorization: Bearer <private API key>`
- n8n workflows required: none

The MCP endpoint uses the same permanent Ripley login, persisted cookie jar,
automatic reauthentication, loopback-only container listener, and Caddy HTTPS
route as the REST API. It does not create a second application stack.

Ten tools are available: account health, metadata, periods, period entries,
single-entry validation, batch validation, single create, bulk create, update,
and delete. All live write tools require `confirm=true`; delete is marked
destructive and all read/validation tools are marked read-only.

Production MCP verification passed:

- MCP initialization and discovery: passed, 10 tools found.
- Bearer authentication and authenticated Ripley health: passed.
- Entry validation: passed.
- Controlled live create/readback: passed.
- Controlled live update/readback: passed.
- Controlled live delete: passed.
- Independent REST absence check: passed.
- Temporary entry `4233094` is absent from period `188309`.
- Container state after verification: running and healthy.
- Unauthenticated public MCP request: HTTP 401 with `WWW-Authenticate: Bearer`.
- Local automated suite: 20 passed.
- Rollback source: `/opt/ripley-api/backups/pre-mcp-20260803`.

This Windows Codex installation is registered globally as MCP server `ripley`.
Its token is stored in the Windows user environment as `RIPLEY_API_KEY`; the
Codex configuration records only that variable name, not the secret value.

## Inspection update

Post-deployment inspection completed after the three branched implementation
chats were merged into this project folder.

**Overall four-priority REST checklist plus MCP extension: 100%**

`[████████████████████] 100%`

- Project inventory reviewed: complete.
- Credential scan: passed; no supplied Ripley username or password was found
  in project files.
- Automated suite: **20 passed**.
- Docker, Compose, secret mounts, loopback binding, API-key validation, and
  automatic authentication structure: verified.
- Authentication and hosted read access are operational.
- The inspection observations below are separate review notes. They do not
  reopen or expand the completed checklist.

### Post-completion inspection observations

1. **Add persistent idempotency and resumable batch state.**
   Current duplicate detection only compares entries inside one request. If a
   request times out after Ripley accepted an entry, replaying the batch can
   create a duplicate.
2. **Serialize Ripley session access and cookie-jar writes.**
   FastAPI shares one cached `requests.Session`. Concurrent callers can race
   through the session and replace the same cookie file.
3. **Make write reauthentication restart the complete form operation.**
   Create/update expiry must fetch a new authenticated form and fresh hidden
   fields before resubmitting. Existing expiry tests prove GET recovery, not an
   interrupted multipart write.
4. **Remove or replace the retired cookie-import startup path.**
   `start.ps1` and `import_session.py` still generate the obsolete
   `RIPLEY_COOKIE` configuration and do not provision the username/password
   files required by the current client.
5. **Optionally repeat the hosted write-cycle test after future changes.**
   Complete one controlled batch create, edit, delete, and absence check using
   the public HTTPS API after findings 1–4 are resolved.

The Starlette/httpx deprecation warning emitted by the test environment is
non-blocking and does not affect the current service.

## Current result

All four priorities are complete. This chat completed Priority 1; the two
branched chats completed Priorities 2 and 3; the final public production cycle
completed Priority 4. The hosted Ripley API stores the account login as
restricted VPS secrets, logs in automatically, persists only the resulting
cookie jar, detects both login-page and home-page expiry redirects,
reauthenticates, and retries the interrupted request once.

- Public API: `https://digi.hopto.me/ripley-api`
- Swagger: `https://digi.hopto.me/ripley-api/docs`
- VPS: `root@87.99.147.219` (`n8n-vps`)
- Service directory: `/opt/ripley-api`
- Container: `ripley-api`
- Private listener: `127.0.0.1:8788`
- n8n workflows required: none

No username, password, API key, or cookie is recorded in this document or the
project source.

## Required-task status

1. **Priority 1 — Permanent authentication: 100% complete**
   - Restricted username/password files: complete.
   - Automatic login using fresh Gravity Forms hidden fields: complete.
   - Persistent restricted cookie jar: complete.
   - Expired-session detection and one automatic retry: complete.
   - Forced-expiration production test: passed.
2. **Priority 2 — Single Docker API service and private API key: complete.**
3. **Priority 3 — Public HTTPS through Caddy: complete.**
4. **Priority 4 — Final hosted public write-cycle verification: complete.**
   - Public batch dry run: passed.
   - Public live batch create and readback: passed.
   - Public live edit and changed-description readback: passed.
   - Public live delete: passed.
   - Scripted and independent absence checks: passed.
   - No temporary test record remains.

## Priority 1 implementation

1. The container reads the Ripley email and password from separate read-only
   files under `/run/secrets`.
2. Host secret files are owned by UID/GID `10001` and use mode `400`.
3. The cookie jar is stored at `/var/lib/ripley-api/session.cookies`, owned by
   UID/GID `10001`, with mode `600`.
4. Login always begins with `GET /login/`, copies Ripley's current hidden form
   state, supplies the stored credentials, and verifies dashboard form 60.
5. Protected requests recognize redirects to either `/login/` or the site home
   page as authentication expiry.
6. Only one thread refreshes the session, and the original request is retried
   once after successful login.
7. Credentials and cookies are excluded from Git, the Docker image, API
   responses, and application logs.
8. The obsolete manually copied cookie secret was permanently removed after
   automatic renewal passed.

## Verification evidence

- Local automated suite: **20 passed**.
- Tests cover cold-start login, cookie reuse after restart, forced expiry,
  home-page expiry redirects, one-time retry, restricted secret loading, and
  credential redaction.
- VPS image build: passed.
- Compose validation: passed.
- Candidate container health check: passed.
- Live container: `running`, `healthy`, user `ripley`.
- Live account health: authenticated; dashboard form 60 available.
- Forced corrupted-cookie test: `FORCED_EXPIRY_REAUTH_OK`.
- Health after forced renewal: passed.
- Public `/ripley-api/healthz`: passed over HTTPS.
- Public authenticated `/ripley-api/health`: passed over HTTPS.
- Priority 4 temporary record: period `188309`, entry `4233070`.
- Public batch create, edit/readback, delete, and absence cycle: passed.
- Independent JSON absence check: entry `4233070` is not present in period
  `188309`.
- Public authenticated health after deletion: passed.
- Existing cookie-only source backup:
  `/opt/ripley-api/backups/priority1-cookie-only-20260803`.

## Checklist completion

There is no remaining checklist work. Priorities 1–4 are complete.

## Post-completion follow-up

1. Rotate the Ripley password because it was entered in the Codex chat, then
   update the two VPS credential files using the provisioning script.
2. If the API is later expanded for concurrent clients or automatic network
   retries, consider persistent idempotency, serialized session writes, and a
   create/update expiry integration test.
3. Remove or replace the retired local cookie-import scripts during the next
   cleanup pass.

## Credential rotation

After changing the password at Ripley:

```bash
ssh root@87.99.147.219
sudo bash /opt/ripley-api/scripts/provision-secrets.sh /opt/ripley-api
cd /opt/ripley-api
docker compose restart
```

Then verify without exposing the API key:

```bash
cd /opt/ripley-api
API_KEY="$(cat secrets/ripley_api_key.txt)"
curl -fsS http://127.0.0.1:8788/health -H "X-API-Key: $API_KEY"
unset API_KEY
```

## Operations

```bash
ssh root@87.99.147.219
cd /opt/ripley-api
docker compose ps
docker compose logs --tail 100
docker compose restart
```

## Main files

- `app.py` — REST routes, MCP tools, API-key enforcement, and Bearer enforcement.
- `ripley_auth.py` — secret loading, login, cookie persistence, and renewal.
- `ripley_client.py` — Ripley CRUD and batch form client.
- `compose.yaml` — secret mounts and persistent session state.
- `Dockerfile` — fixed non-root UID/GID runtime.
- `scripts/provision-secrets.sh` — terminal-based credential rotation.
- `scripts/provision-vps-credentials.ps1` — optional Windows provisioning path.
- `scripts/verify-session-renewal.py` — forced-expiration verification.
- `scripts/verify-public-write-cycle.py` — Priority 4 public CRUD cycle.
- `scripts/verify-public-absence.py` — independent read-only absence check.
- `scripts/verify-public-mcp.py` — public MCP discovery and controlled CRUD cycle.
- `tests/` — API, parsing, authentication, and safety tests.
