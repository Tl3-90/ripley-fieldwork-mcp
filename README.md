# Ripley Fieldwork API + MCP

Private REST API and MCP server for a Ripley Fieldwork Tracker account. It supports account metadata, periods, entries, JSON/CSV batch creation, editing, and confirmed deletion.

## AI agent quick context

This repository wraps one configured Ripley Fieldwork Tracker account. The
hosted service exposes traditional REST routes for scripts and a Streamable
HTTP MCP endpoint for AI clients. Ripley itself does not provide this MCP
interface.

An AI agent working with this repository should follow these rules:

1. Never request, print, commit, or log the Ripley username, password, session
   cookie, API key, or Bearer token.
2. Call `ripley_get_metadata` before constructing entries. Never guess
   `supervisor_id` or `organization_id`.
3. Validate entries before any live write.
4. Show validation failures or duplicates to the user before submission.
5. Only call create, bulk-create, update, or delete after explicit user
   approval; pass `confirm=true`.
6. Use `ripley_list_entries` after a write when readback verification matters.
7. Prefer `ripley_bulk_create_entries` for multiple entries. Ripley processes
   entries sequentially, and the result reports success or failure per item.

### MCP connection

```text
AI client
  -> HTTPS Streamable HTTP MCP
  -> https://digi.hopto.me/ripley-api/mcp
  -> Authorization: Bearer <private API key>
  -> hosted Ripley service
  -> automatic Ripley session renewal
  -> configured Ripley account
```

### MCP tool contract

| Tool | Mode | Purpose |
|---|---|---|
| `ripley_check_health` | Read | Verify the stored Ripley login and renewal path. |
| `ripley_get_metadata` | Read | Return valid supervisor and organization IDs and allowed values. |
| `ripley_list_periods` | Read | List monthly periods and their IDs. |
| `ripley_list_entries` | Read | List all entries for one period. |
| `ripley_validate_entry` | Read | Normalize and validate one entry without writing. |
| `ripley_validate_batch` | Read | Validate up to 500 entries and detect in-request duplicates. |
| `ripley_create_entry` | Write | Create one entry; requires `confirm=true`. |
| `ripley_bulk_create_entries` | Write | Create up to 500 entries sequentially; requires `confirm=true`. |
| `ripley_update_entry` | Write | Replace one entry by `hours_id`; requires `confirm=true`. |
| `ripley_delete_entry` | Destructive | Delete one entry by `hours_id` and `period_id`; requires `confirm=true`. |

### Entry payload

```json
{
  "date": "2026-08-03",
  "start_time": "09:00",
  "end_time": "11:00",
  "supervisor_id": "ID_FROM_METADATA",
  "organization_id": "ID_FROM_METADATA",
  "hour_type": "Independent",
  "independent_restricted": 0,
  "independent_unrestricted": 2,
  "supervised_individual_restricted": 0,
  "supervised_individual_unrestricted": 0,
  "supervised_group_unrestricted": 0,
  "observation_time": 0,
  "contact_type": null,
  "format_type": null,
  "description": "Fieldwork description"
}
```

Accepted values:

- `hour_type`: `Independent` or `Supervised`
- `contact_type`: `Contact` or `Observation`
- `format_type`: `In-Person`, `Online`, or `Phone Call`
- Supervised entries require `contact_type` and `format_type`.
- Independent entries cannot allocate supervised hours, and supervised entries
  cannot allocate independent hours.
- Allocated hours must equal the elapsed start-to-end duration.
- `observation_time` cannot exceed the entry duration.
- Dates accept `YYYY-MM-DD` or `MM/DD/YYYY`; times accept 24-hour `HH:MM` or
  12-hour values such as `4:30 PM`.

## Architecture

```text
Caddy HTTPS
  -> 127.0.0.1:8788
  -> one non-root FastAPI/FastMCP container
  -> shared Ripley client
  -> persistent cookie jar
  -> automatic login and one retry after session expiry
```

The REST and MCP interfaces are served by the same process and use the same
validation and Ripley client. No n8n workflow is required.

## Container

The production package is one non-root Docker container. It listens on
container port `8000`; Compose publishes it only to VPS loopback at
`127.0.0.1:8788` so Caddy can expose it through HTTPS.

Every account endpoint requires:

```http
X-API-Key: your-private-key
```

The remote MCP endpoint is:

```text
https://digi.hopto.me/ripley-api/mcp
```

MCP clients use the same private key as a standard Bearer token:

```http
Authorization: Bearer your-private-key
```

The API key and Ripley login credentials are mounted as read-only runtime secrets. They are excluded from Git and the Docker image. The resulting cookie jar is stored separately in `state/` and is refreshed automatically when Ripley expires it.

## Prepare runtime secrets

From the project directory on the server:

```bash
sudo bash scripts/provision-secrets.sh /opt/ripley-api
```

The prompt reads the Ripley email and password directly from the VPS terminal. The password is hidden and neither value is echoed or logged. The API key remains the only credential used by API clients.

At cold start, the service first reuses the restricted cookie jar when it is still valid. If Ripley returns the login form, the service fetches fresh hidden login fields, authenticates using the stored credentials, saves the new cookie jar, and retries the original request once.

## Build and start

```bash
docker compose build
docker compose up -d
docker compose ps
```

The unauthenticated `/healthz` endpoint reports only whether the container process is running. `/health` checks the actual Ripley account session and requires the private API key.

```bash
API_KEY="$(cat secrets/ripley_api_key.txt)"
curl -fsS http://127.0.0.1:8788/healthz
curl -fsS http://127.0.0.1:8788/health -H "X-API-Key: $API_KEY"
```

## Safe write behavior

- `POST /entries` defaults to `dry_run=true`.
- `PUT /entries/{hours_id}` defaults to `dry_run=true`.
- `POST /entries/bulk` uses the `dry_run` property in its JSON body.
- `POST /entries/bulk/csv` defaults to `dry_run=true`.
- `DELETE /entries/{hours_id}` defaults to `confirm=false`.

Validate first, then explicitly enable the live operation.

## MCP tools

The MCP endpoint provides ten purpose-built AI tools:

1. `ripley_check_health`
2. `ripley_get_metadata`
3. `ripley_list_periods`
4. `ripley_list_entries`
5. `ripley_validate_entry`
6. `ripley_validate_batch`
7. `ripley_create_entry`
8. `ripley_bulk_create_entries`
9. `ripley_update_entry`
10. `ripley_delete_entry`

Create, bulk-create, update, and delete require `confirm=true`. Read and validation tools are explicitly marked read-only in their MCP annotations. The JSON/CSV REST routes remain available for normal scripts; AI clients should prefer the structured MCP tools.

### One-click Codex setup on Windows

This is the simplest setup for the intended user and does not require a
terminal:

1. Install Codex and sign in once.
2. Download and extract this private repository.
3. Double-click `INSTALL-RIPLEY-MCP.cmd`.
4. Paste the private bearer token when prompted. It is hidden while being
   entered and is saved only to the Windows user environment.
5. Close Codex completely and reopen it.
6. Start a new chat and say: `Check my Ripley connection.`

The installer registers the hosted MCP in the user's standard Codex
configuration, verifies the live Ripley account connection, and preserves a
backup of any existing Codex configuration. It does not install another server,
Docker image, workflow, or local MCP process. Never place the bearer token in
GitHub.

### One-click Codex setup on macOS

No GitHub account or terminal work is required if Thomas sends the installer
file directly:

1. Install Codex and sign in once.
2. Double-click `INSTALL-RIPLEY-MCP-MAC.command`.
3. Paste the private bearer token when prompted. It is hidden while being
   entered and is stored in macOS Keychain.
4. Close Codex completely and reopen it.
5. Start a new chat and say: `Check my Ripley connection.`

The Mac installer is a single file. It registers the hosted MCP in Codex,
verifies the live Ripley account connection, and installs a user LaunchAgent
that restores the Keychain-backed token after login or restart. If macOS blocks
the first double-click because the file was downloaded, Control-click the file,
choose **Open**, and confirm **Open** once.

If Codex is already installed, the intended user can instead attach the
personalized ZIP to a Codex chat and ask Codex to install it. The agent should
extract the ZIP, run the included `.command` file, verify the Ripley entry in
`~/.codex/config.toml`, and avoid printing the embedded token. After the agent
finishes, fully quit and reopen Codex, then call `ripley_check_health` from a new
chat. The installer automatically skips interactive pauses when an agent runs
it without a terminal.

Thomas can create a personalized ZIP that includes the bearer token by running
`scripts/build-personalized-mac-package.ps1` on the configured Windows PC. The
resulting ZIP is intentionally created outside the repository and must never be
committed or uploaded because it grants live Ripley write access.

### Codex CLI

Keep the token in an environment variable, then register the hosted endpoint:

```powershell
$env:RIPLEY_API_KEY = Get-Content C:\secure\ripley_api_key.txt -Raw
codex mcp add ripley --url https://digi.hopto.me/ripley-api/mcp --bearer-token-env-var RIPLEY_API_KEY
```

### Claude Desktop or another remote MCP client

Use the MCP URL above and configure this request header through the client's secret/header setting:

```text
Authorization: Bearer <private API key>
```

Do not paste the Ripley username, Ripley password, WordPress cookie, or API key into an AI prompt. Only the MCP client configuration needs the private API key.

## Example requests

```bash
curl -fsS http://127.0.0.1:8788/metadata -H "X-API-Key: $API_KEY"
curl -fsS http://127.0.0.1:8788/periods -H "X-API-Key: $API_KEY"

curl -fsS -X POST http://127.0.0.1:8788/entries/bulk \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @examples/bulk_entries.json

curl -fsS -X POST 'http://127.0.0.1:8788/entries/bulk/csv?dry_run=true' \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: text/csv" \
  --data-binary @examples/bulk_entries.csv
```

## Stop

```bash
docker compose down
```

Container restart policy is `unless-stopped`. Ripley writes remain sequential because Ripley processes its form one entry at a time.
