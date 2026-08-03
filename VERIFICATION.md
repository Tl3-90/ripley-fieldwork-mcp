# Ripley Account API Verification

Verified on August 3, 2026.

## Hosted MCP verification

The MCP endpoint at `https://digi.hopto.me/ripley-api/mcp` passed a production
Streamable HTTP client test using the server-held private API key as a Bearer
token.

- MCP initialization passed.
- Exactly ten expected Ripley tools were discovered.
- Tool safety annotations were present.
- Authenticated account health passed.
- Metadata and entry validation passed.
- A controlled temporary entry was created and read back through MCP.
- The same entry was updated and the changed description was read back.
- The entry was deleted through MCP.
- MCP absence verification passed.
- An independent REST check confirmed hours ID `4233094` is absent from period
  `188309`.
- No MCP verification record remains.
- Requests without a token return HTTP 401 and `WWW-Authenticate: Bearer`.
- The final container is running and healthy as non-root user `ripley`.

Current automated result: **20 tests passed**.

## Passed

- Python syntax compilation for all application modules.
- FastAPI/Requests/Beautiful Soup/runtime dependency imports.
- API server startup on localhost.
- OpenAPI document generation for version 1.0.0.
- `X-API-Key` rejection when the key is absent.
- Read endpoint routing for health, metadata, periods, and period entries.
- Safe defaults for create, update, and delete operations.
- JSON bulk submission routing.
- CSV bulk parsing and submission routing.
- Entry date/time normalization.
- Elapsed-time versus allocated-hours validation.
- Duplicate detection inside bulk payloads.
- Dashboard supervisor/organization/period parsing.
- Period hour-entry parsing.

Automated result: **8 tests passed**.

Current post-deployment automated result: **17 tests passed**.

## Live-site evidence

The signed-in Ripley pages were inspected without modifying records. The live site currently exposes:

- Gravity Forms form `60` for create and edit;
- dynamic form state that must be fetched immediately before each write;
- `/dashboard/period/?period_id=...` for month records;
- `/dashboard/edit-hours/?hours_id=...` for edits;
- `/delete-hours/?hours_id=...&redirect=periodHours&period_id=...` for deletion;
- the mapped supervisor, organization, time-allocation, contact, format, and description fields used by this package.

## Live account verification

Authenticated live checks passed:

- signed-in session accepted;
- dashboard form `60` available;
- six supervisors and four organizations read;
- ten existing periods read;
- thirty records parsed from the sampled period;
- create, update, and delete dry-runs passed;
- a controlled temporary entry was created and assigned a real Ripley ID;
- that entry was edited and the changed description was read back;
- the entry was deleted;
- the deleted entry was confirmed absent;
- Ripley automatically removed the resulting empty temporary month.

The account was returned to its pre-test record state.

## Hosted public API verification — Priority 4

Priority 4 was completed through `https://digi.hopto.me/ripley-api` using the
server-held API key. The controlled temporary entry used period ID `188309`
and hours ID `4233070`.

- JSON batch dry run passed.
- Live JSON batch create passed.
- The created entry was read back through the public API.
- Live edit passed and the changed description was read back.
- Live delete passed.
- The verification script confirmed the entry was absent.
- A separate JSON-based read-only check confirmed entry `4233070` was not
  present in period `188309`.
- Authenticated public health passed after deletion.
- No temporary Priority 4 record remains.

## Fixes found during live verification

- Chrome's PowerShell request export is now accepted by `import_session.py`.
- Advertising and Stripe cookies are discarded; only the WordPress login cookie is retained.
- Ripley's relative Gravity Forms action is resolved against the site URL before submission.
- Write requests send browser-equivalent `Referer` and `Origin` headers.
- Deleting the final entry in a month is treated as successful when Ripley removes that empty month.

## Security follow-up

The Ripley password was entered in chat during permanent-authentication setup.
Rotate it at Ripley, then update the VPS secret files with
`sudo bash /opt/ripley-api/scripts/provision-secrets.sh /opt/ripley-api` and
restart the container. The retired browser-cookie import path is no longer used
by production.
