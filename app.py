from __future__ import annotations

import csv
import hmac
import io
import os
from functools import lru_cache
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from models import BulkEntryRequest, EntryPayload, UpdateEntryRequest
from ripley_auth import AuthenticationError, load_credentials, read_secret
from ripley_client import (
    RipleyClient,
    RipleyError,
    ValidationError,
    duplicate_fingerprints,
)


load_dotenv()

mcp = FastMCP(
    name="Ripley Account Tools",
    version="1.0.0",
    instructions=(
        "Private tools for the configured Ripley Fieldwork Tracker account. "
        "Read metadata before creating entries so supervisor_id and "
        "organization_id are valid. Validate entries before live writes. "
        "Create, update, bulk-create, and delete tools require confirm=true."
    ),
    mask_error_details=True,
    on_duplicate="error",
)
mcp_app = mcp.http_app(path="/mcp")

app = FastAPI(
    title="Ripley Account API",
    version="1.2.0",
    description=(
        "Private REST and MCP wrapper for the signed-in Ripley Fieldwork "
        "Tracker account."
    ),
    root_path=os.getenv("RIPLEY_ROOT_PATH", "").rstrip("/"),
    routes=[*mcp_app.routes],
    lifespan=mcp_app.lifespan,
)


def load_api_key() -> str:
    try:
        return read_secret(
            "RIPLEY_API_KEY",
            "RIPLEY_API_KEY_FILE",
            default_file="/run/secrets/ripley_api_key",
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = load_api_key()
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid X-API-Key")


def _is_mcp_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


@app.middleware("http")
async def protect_mcp(request: Request, call_next):
    """Require a standard Bearer token and reject unexpected browser origins."""
    path = str(request.scope.get("path", request.url.path))
    if not _is_mcp_path(path):
        return await call_next(request)

    allowed_origin = os.getenv("RIPLEY_MCP_ALLOWED_ORIGIN", "https://digi.hopto.me")
    origin = request.headers.get("origin")
    if origin and origin != allowed_origin:
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})

    try:
        expected = load_api_key()
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    scheme, separator, token = request.headers.get("authorization", "").partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not token
        or not hmac.compare_digest(token, expected)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid Bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


@lru_cache(maxsize=1)
def get_client() -> RipleyClient:
    return RipleyClient(
        load_credentials(),
        base_url=os.getenv("RIPLEY_BASE_URL", "https://ripleyfieldworktracker.com"),
        cookie_jar_path=os.getenv(
            "RIPLEY_COOKIE_JAR", "/var/lib/ripley-api/session.cookies"
        ),
    )


def client_dependency(_: None = Depends(require_api_key)) -> RipleyClient:
    try:
        return get_client()
    except (AuthenticationError, RipleyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def call(action):
    try:
        return action()
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RipleyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/healthz", include_in_schema=False)
def container_health():
    return {"status": "ok"}


@app.get("/health")
def health(client: RipleyClient = Depends(client_dependency)):
    return call(client.status)


@app.get("/metadata")
def metadata(client: RipleyClient = Depends(client_dependency)):
    return call(client.metadata)


@app.get("/periods")
def periods(client: RipleyClient = Depends(client_dependency)):
    return call(client.list_periods)


@app.get("/periods/{period_id}/entries")
def entries(period_id: str, client: RipleyClient = Depends(client_dependency)):
    return call(lambda: client.list_entries(period_id))


@app.post("/entries")
def create_entry(
    payload: EntryPayload,
    dry_run: bool = Query(default=True),
    client: RipleyClient = Depends(client_dependency),
):
    return call(lambda: client.create_entry(payload, dry_run=dry_run))


def _bulk_execute(request: BulkEntryRequest, client: RipleyClient) -> dict[str, Any]:
    if not request.allow_duplicates:
        duplicates = duplicate_fingerprints(request.entries)
        if duplicates:
            raise ValidationError(
                f"Bulk payload contains {len(duplicates)} duplicate entries; set allow_duplicates=true to permit them"
            )
    results = []
    for index, entry in enumerate(request.entries):
        try:
            result = client.create_entry(entry, dry_run=request.dry_run)
            results.append({"index": index, **result})
        except Exception as exc:
            results.append({"index": index, "ok": False, "error": str(exc)})
            if request.stop_on_error:
                break
    return {
        "ok": all(result.get("ok") for result in results),
        "dry_run": request.dry_run,
        "requested": len(request.entries),
        "processed": len(results),
        "succeeded": sum(1 for result in results if result.get("ok")),
        "results": results,
    }


@app.post("/entries/bulk")
def bulk_create(
    payload: BulkEntryRequest,
    client: RipleyClient = Depends(client_dependency),
):
    return call(lambda: _bulk_execute(payload, client))


def _clean_csv_row(row: dict[str, str | None]) -> dict[str, Any]:
    numeric = {
        "independent_restricted", "independent_unrestricted",
        "supervised_individual_restricted", "supervised_individual_unrestricted",
        "supervised_group_unrestricted", "observation_time",
    }
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        value = (value or "").strip()
        if key in numeric:
            cleaned[key] = float(value) if value else 0
        elif key in {"contact_type", "format_type"} and not value:
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


@app.post("/entries/bulk/csv")
def bulk_create_csv(
    csv_text: str = Body(media_type="text/csv"),
    dry_run: bool = Query(default=True),
    stop_on_error: bool = Query(default=True),
    allow_duplicates: bool = Query(default=False),
    client: RipleyClient = Depends(client_dependency),
):
    try:
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        entries = [EntryPayload(**_clean_csv_row(row)) for row in rows]
        request = BulkEntryRequest(
            entries=entries,
            dry_run=dry_run,
            stop_on_error=stop_on_error,
            allow_duplicates=allow_duplicates,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid CSV: {exc}") from exc
    return call(lambda: _bulk_execute(request, client))


@app.put("/entries/{hours_id}")
def update_entry(
    hours_id: str,
    payload: UpdateEntryRequest,
    dry_run: bool = Query(default=True),
    client: RipleyClient = Depends(client_dependency),
):
    return call(lambda: client.update_entry(hours_id, payload, dry_run=dry_run))


@app.delete("/entries/{hours_id}")
def delete_entry(
    hours_id: str,
    period_id: str = Query(...),
    confirm: bool = Query(default=False),
    client: RipleyClient = Depends(client_dependency),
):
    return call(lambda: client.delete_entry(hours_id, period_id, confirm=confirm))


def mcp_call(action):
    """Translate expected Ripley failures into safe, useful MCP tool errors."""
    try:
        return action()
    except AuthenticationError as exc:
        raise ToolError(f"Ripley authentication failed: {exc}") from exc
    except ValidationError as exc:
        raise ToolError(f"Ripley validation failed: {exc}") from exc
    except RipleyError as exc:
        raise ToolError(f"Ripley request failed: {exc}") from exc


def require_confirmation(confirm: bool, operation: str) -> None:
    if confirm is not True:
        raise ToolError(
            f"{operation} was not performed. Set confirm=true only after reviewing "
            "the target data."
        )


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
DELETE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


@mcp.tool(
    name="ripley_check_health",
    title="Check Ripley Account Health",
    annotations=READ_ONLY,
)
def mcp_check_health() -> dict[str, Any]:
    """Verify the stored Ripley login and automatic session renewal are working."""
    return mcp_call(lambda: get_client().status())


@mcp.tool(
    name="ripley_get_metadata",
    title="Get Ripley Metadata",
    annotations=READ_ONLY,
)
def mcp_get_metadata() -> dict[str, Any]:
    """Return valid supervisor and organization IDs plus allowed entry values."""
    return mcp_call(lambda: get_client().metadata())


@mcp.tool(
    name="ripley_list_periods",
    title="List Ripley Periods",
    annotations=READ_ONLY,
)
def mcp_list_periods() -> dict[str, Any]:
    """List the account's available monthly periods and their Ripley IDs."""
    periods_result = mcp_call(lambda: get_client().list_periods())
    return {"count": len(periods_result), "periods": periods_result}


@mcp.tool(
    name="ripley_list_entries",
    title="List Ripley Entries",
    annotations=READ_ONLY,
)
def mcp_list_entries(
    period_id: Annotated[
        str,
        Field(min_length=1, description="Ripley period ID returned by ripley_list_periods"),
    ],
) -> dict[str, Any]:
    """List all fieldwork entries in one Ripley period."""
    return mcp_call(lambda: get_client().list_entries(period_id))


@mcp.tool(
    name="ripley_validate_entry",
    title="Validate Ripley Entry",
    annotations=READ_ONLY,
)
def mcp_validate_entry(entry: EntryPayload) -> dict[str, Any]:
    """Validate and normalize one entry without writing anything to Ripley."""
    return mcp_call(lambda: get_client().create_entry(entry, dry_run=True))


@mcp.tool(
    name="ripley_validate_batch",
    title="Validate Ripley Entry Batch",
    annotations=READ_ONLY,
)
def mcp_validate_batch(
    entries: Annotated[list[EntryPayload], Field(min_length=1, max_length=500)],
    allow_duplicates: Annotated[
        bool,
        Field(description="Permit identical entries inside this batch"),
    ] = False,
) -> dict[str, Any]:
    """Validate up to 500 entries and detect in-batch duplicates without writing."""
    request = BulkEntryRequest(
        entries=entries,
        dry_run=True,
        stop_on_error=False,
        allow_duplicates=allow_duplicates,
    )
    return mcp_call(lambda: _bulk_execute(request, get_client()))


@mcp.tool(
    name="ripley_create_entry",
    title="Create Ripley Entry",
    annotations=WRITE,
)
def mcp_create_entry(entry: EntryPayload, confirm: bool) -> dict[str, Any]:
    """Create one live entry. Call ripley_validate_entry first; confirm must be true."""
    require_confirmation(confirm, "Create")
    return mcp_call(lambda: get_client().create_entry(entry, dry_run=False))


@mcp.tool(
    name="ripley_bulk_create_entries",
    title="Bulk Create Ripley Entries",
    annotations=WRITE,
)
def mcp_bulk_create_entries(
    entries: Annotated[list[EntryPayload], Field(min_length=1, max_length=500)],
    confirm: bool,
    stop_on_error: Annotated[
        bool,
        Field(description="Stop after the first failed entry"),
    ] = True,
    allow_duplicates: Annotated[
        bool,
        Field(description="Permit identical entries inside this batch"),
    ] = False,
) -> dict[str, Any]:
    """Create up to 500 entries sequentially. Validate first; confirm must be true."""
    require_confirmation(confirm, "Bulk create")
    request = BulkEntryRequest(
        entries=entries,
        dry_run=False,
        stop_on_error=stop_on_error,
        allow_duplicates=allow_duplicates,
    )
    return mcp_call(lambda: _bulk_execute(request, get_client()))


@mcp.tool(
    name="ripley_update_entry",
    title="Update Ripley Entry",
    annotations=WRITE,
)
def mcp_update_entry(
    hours_id: Annotated[
        str,
        Field(min_length=1, description="Ripley hours ID returned by ripley_list_entries"),
    ],
    entry: UpdateEntryRequest,
    confirm: bool,
) -> dict[str, Any]:
    """Replace one live entry. Validate the replacement first; confirm must be true."""
    require_confirmation(confirm, "Update")
    return mcp_call(lambda: get_client().update_entry(hours_id, entry, dry_run=False))


@mcp.tool(
    name="ripley_delete_entry",
    title="Delete Ripley Entry",
    annotations=DELETE,
)
def mcp_delete_entry(
    hours_id: Annotated[
        str,
        Field(min_length=1, description="Exact Ripley hours ID to delete"),
    ],
    period_id: Annotated[
        str,
        Field(min_length=1, description="Period containing the target entry"),
    ],
    confirm: bool,
) -> dict[str, Any]:
    """Permanently delete one entry after verifying its hours and period IDs."""
    require_confirmation(confirm, "Delete")
    return mcp_call(
        lambda: get_client().delete_entry(hours_id, period_id, confirm=True)
    )


# The MCP route is merged above instead of mounted so Starlette can match it
# correctly when Caddy strips /ripley-api and FastAPI supplies that root_path.
# Public endpoint: https://digi.hopto.me/ripley-api/mcp
