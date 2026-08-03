from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from models import EntryPayload
from ripley_auth import (
    AuthenticatedRipleySession,
    AuthenticationError,
    RipleyCredentials,
)


class RipleyError(RuntimeError):
    pass


class ValidationError(RipleyError):
    pass


@dataclass(frozen=True)
class NormalizedEntry:
    date_display: str
    start_parts: tuple[str, str, str]
    end_parts: tuple[str, str, str]
    duration: float
    allocated: float
    source: EntryPayload

    @property
    def fingerprint(self) -> str:
        raw = "|".join(
            [
                self.date_display,
                *self.start_parts,
                *self.end_parts,
                self.source.supervisor_id,
                self.source.organization_id,
                self.source.hour_type,
                f"{self.allocated:.3f}",
                self.source.description.strip(),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _parse_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValidationError(f"Invalid date {value!r}; use YYYY-MM-DD or MM/DD/YYYY")


def _parse_time(value: str) -> datetime:
    clean = value.strip().upper()
    for fmt in ("%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    raise ValidationError(f"Invalid time {value!r}; use HH:MM or h:mm AM/PM")


def _time_parts(value: str) -> tuple[str, str, str, datetime]:
    parsed = _parse_time(value)
    am_pm = "pm" if parsed.hour >= 12 else "am"
    return str(parsed.hour % 12 or 12), f"{parsed.minute:02d}", am_pm, parsed


def normalize_entry(entry: EntryPayload) -> NormalizedEntry:
    date = _parse_date(entry.date)
    sh, sm, sap, start = _time_parts(entry.start_time)
    eh, em, eap, end = _time_parts(entry.end_time)
    duration = (end - start).total_seconds() / 3600
    if duration <= 0:
        raise ValidationError("End time must be after start time on the same day")

    independent = entry.independent_restricted + entry.independent_unrestricted
    supervised = (
        entry.supervised_individual_restricted
        + entry.supervised_individual_unrestricted
        + entry.supervised_group_unrestricted
    )
    if entry.hour_type == "Independent":
        if supervised:
            raise ValidationError("Independent entries cannot allocate supervised hours")
        allocated = independent
    else:
        if independent:
            raise ValidationError("Supervised entries cannot allocate independent hours")
        if not entry.contact_type or not entry.format_type:
            raise ValidationError("Supervised entries require contact_type and format_type")
        allocated = supervised
    if abs(duration - allocated) > 0.011:
        raise ValidationError(
            f"Allocated hours ({allocated:.3f}) must equal elapsed time ({duration:.3f})"
        )
    if entry.observation_time > duration + 0.011:
        raise ValidationError("observation_time cannot exceed elapsed time")
    return NormalizedEntry(
        date_display=date.strftime("%m/%d/%Y"),
        start_parts=(sh, sm, sap),
        end_parts=(eh, em, eap),
        duration=round(duration, 3),
        allocated=round(allocated, 3),
        source=entry,
    )


class RipleyClient:
    def __init__(
        self,
        credentials: RipleyCredentials,
        *,
        base_url: str = "https://ripleyfieldworktracker.com",
        cookie_jar_path: str | Path = "/var/lib/ripley-api/session.cookies",
        auth_session: AuthenticatedRipleySession | None = None,
    ) -> None:
        self.auth = auth_session or AuthenticatedRipleySession(
            credentials,
            base_url=base_url,
            cookie_jar_path=cookie_jar_path,
        )
        self.base_url = self.auth.base_url

    def _url(self, path: str) -> str:
        return self.auth.url(path)

    def _get(self, path: str):
        return self.auth.request("GET", path)

    def status(self) -> dict[str, Any]:
        response = self._get("/dashboard/")
        form_available = BeautifulSoup(response.text, "html.parser").select_one("#gform_60") is not None
        if not form_available:
            raise AuthenticationError("Authenticated dashboard form was not found")
        return {
            "authenticated": True,
            "dashboard_url": response.url,
            "form_60_available": True,
            "automatic_reauthentication": True,
        }

    def metadata(self) -> dict[str, Any]:
        soup = BeautifulSoup(self._get("/dashboard/").text, "html.parser")
        return {
            "supervisors": self._select_options(soup, "input_60_42"),
            "organizations": self._select_options(soup, "input_60_51"),
            "field_contract": {
                "hour_types": ["Independent", "Supervised"],
                "contact_types": ["Contact", "Observation"],
                "format_types": ["In-Person", "Online", "Phone Call"],
            },
        }

    @staticmethod
    def _select_options(soup: BeautifulSoup, select_id: str) -> list[dict[str, Any]]:
        select = soup.select_one(f"#{select_id}")
        if not select:
            return []
        result = []
        for option in select.select("option"):
            value = option.get("value", "")
            if value.startswith("+"):
                continue
            result.append(
                {
                    "id": value,
                    "name": option.get_text(" ", strip=True),
                    "selected": option.has_attr("selected"),
                }
            )
        return result

    def list_periods(self) -> list[dict[str, str]]:
        soup = BeautifulSoup(self._get("/dashboard/").text, "html.parser")
        periods: dict[str, dict[str, str]] = {}
        for anchor in soup.select('a[href*="/dashboard/period/"][href*="period_id="]'):
            href = anchor.get("href", "")
            period_id = parse_qs(urlparse(href).query).get("period_id", [""])[0]
            if period_id:
                periods[period_id] = {
                    "period_id": period_id,
                    "label": " ".join(anchor.stripped_strings),
                    "url": self._url(href),
                }
        return list(periods.values())

    def list_entries(self, period_id: str) -> dict[str, Any]:
        soup = BeautifulSoup(
            self._get(f"/dashboard/period/?period_id={period_id}").text, "html.parser"
        )
        table = self._entry_table(soup)
        if table is None:
            raise RipleyError(f"No entry table found for period {period_id}")
        entries: list[dict[str, Any]] = []
        rows = table.select("tr")
        for index, row in enumerate(rows):
            edit = row.select_one("a.editHours[hours_id]")
            if edit is None:
                continue
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if len(cells) < 9:
                continue
            description = ""
            if index + 1 < len(rows) and rows[index + 1].select_one("a.editHours") is None:
                next_cells = rows[index + 1].select("td")
                if len(next_cells) == 1:
                    description = next_cells[0].get_text(" ", strip=True)
            hours_id = edit.get("hours_id", "")
            entries.append(
                {
                    "hours_id": hours_id,
                    "period_id": str(period_id),
                    "date": cells[0],
                    "start_time": cells[1],
                    "end_time": cells[2],
                    "supervisor": cells[3],
                    "independent_restricted": self._number(cells[4]),
                    "independent_unrestricted": self._number(cells[5]),
                    "supervised_individual_restricted": self._number(cells[6]),
                    "supervised_individual_unrestricted": self._number(cells[7]),
                    "supervised_group_unrestricted": self._number(cells[8]),
                    "contact_type": cells[9] if len(cells) > 9 and cells[9] else None,
                    "format_type": cells[10] if len(cells) > 10 and cells[10] else None,
                    "description": description,
                }
            )
        return {"period_id": str(period_id), "count": len(entries), "entries": entries}

    @staticmethod
    def _number(value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _entry_table(soup: BeautifulSoup) -> Tag | None:
        for table in soup.select("table"):
            headers = " ".join(th.get_text(" ", strip=True) for th in table.select("th"))
            if "Date" in headers and "Start Time" in headers and "Restricted" in headers:
                return table
        return None

    def create_entry(self, entry: EntryPayload, dry_run: bool = True) -> dict[str, Any]:
        normalized = normalize_entry(entry)
        return self._dry_run_result(normalized, "create") if dry_run else self._submit_entry(
            "/dashboard/", normalized, "create"
        )

    def update_entry(
        self, hours_id: str, entry: EntryPayload, dry_run: bool = True
    ) -> dict[str, Any]:
        normalized = normalize_entry(entry)
        if dry_run:
            result = self._dry_run_result(normalized, "update")
        else:
            result = self._submit_entry(
                f"/dashboard/edit-hours/?hours_id={hours_id}", normalized, "update"
            )
        result["hours_id"] = str(hours_id)
        return result

    @staticmethod
    def _dry_run_result(normalized: NormalizedEntry, operation: str) -> dict[str, Any]:
        return {
            "ok": True,
            "dry_run": True,
            "operation": operation,
            "duration": normalized.duration,
            "allocated": normalized.allocated,
            "fingerprint": normalized.fingerprint,
            "normalized_date": normalized.date_display,
            "normalized_start": ":".join(normalized.start_parts[:2])
            + " "
            + normalized.start_parts[2].upper(),
            "normalized_end": ":".join(normalized.end_parts[:2])
            + " "
            + normalized.end_parts[2].upper(),
        }

    def _submit_entry(
        self, path: str, normalized: NormalizedEntry, operation: str
    ) -> dict[str, Any]:
        page = self._get(path)
        form = BeautifulSoup(page.text, "html.parser").select_one("#gform_60")
        if form is None:
            raise RipleyError("Ripley entry form 60 was not found")
        target_url = urljoin(page.url, (form.get("action") or page.url).split("#", 1)[0])
        override_names = {
            "input_42", "input_51", "input_1", "input_2[]", "input_3[]", "input_57",
            "input_8", "input_9", "input_12", "input_13", "input_24", "input_62",
            "input_46", "input_54", "input_4", "input_60",
        }
        pairs = [
            (name, value)
            for name, value in AuthenticatedRipleySession._form_pairs(form)
            if name not in override_names
        ]
        source = normalized.source
        pairs.extend(
            [
                ("input_42", source.supervisor_id),
                ("input_51", source.organization_id),
                ("input_1", normalized.date_display),
                *[("input_2[]", part) for part in normalized.start_parts],
                *[("input_3[]", part) for part in normalized.end_parts],
                ("input_57", source.hour_type),
                ("input_8", self._decimal(source.independent_restricted)),
                ("input_9", self._decimal(source.independent_unrestricted)),
                ("input_12", self._decimal(source.supervised_individual_restricted)),
                ("input_13", self._decimal(source.supervised_individual_unrestricted)),
                ("input_24", self._decimal(source.supervised_group_unrestricted)),
                ("input_62", self._decimal(source.observation_time)),
                ("input_4", source.description),
                ("input_60", "TRUE"),
            ]
        )
        if source.hour_type == "Supervised":
            pairs.extend(
                [("input_46", source.contact_type or ""), ("input_54", source.format_type or "")]
            )
        response = self.auth.request(
            "POST",
            target_url,
            files=[(name, (None, value)) for name, value in pairs],
            headers={"Referer": page.url, "Origin": self.base_url},
            timeout=45,
        )
        if "gform_validation_error" in response.text:
            raise ValidationError(
                f"Ripley rejected the entry: {self._validation_message(response.text)}"
            )
        period_match = re.search(r"period_id(?:=|%3D)(\d+)", response.text)
        return {
            "ok": True,
            "dry_run": False,
            "operation": operation,
            "fingerprint": normalized.fingerprint,
            "response_url": response.url,
            "period_id": period_match.group(1) if period_match else None,
        }

    @staticmethod
    def _decimal(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"

    @staticmethod
    def _validation_message(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        messages = [node.get_text(" ", strip=True) for node in soup.select(".validation_message")]
        return "; ".join(messages) or "validation error"

    def delete_entry(self, hours_id: str, period_id: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            return {
                "ok": True,
                "dry_run": True,
                "operation": "delete",
                "hours_id": str(hours_id),
                "period_id": str(period_id),
            }
        before = self.list_entries(period_id)
        if not any(item["hours_id"] == str(hours_id) for item in before["entries"]):
            raise RipleyError(f"Entry {hours_id} was not found in period {period_id}")
        self._get(
            f"/delete-hours/?hours_id={hours_id}&redirect=periodHours&period_id={period_id}"
        )
        remaining_period_ids = {item["period_id"] for item in self.list_periods()}
        remains = False
        if str(period_id) in remaining_period_ids:
            remains = any(
                item["hours_id"] == str(hours_id)
                for item in self.list_entries(period_id)["entries"]
            )
        if remains:
            raise RipleyError("Ripley did not delete the entry")
        return {
            "ok": True,
            "dry_run": False,
            "operation": "delete",
            "hours_id": str(hours_id),
            "period_id": str(period_id),
        }


def duplicate_fingerprints(entries: Iterable[EntryPayload]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for entry in entries:
        fingerprint = normalize_entry(entry).fingerprint
        if fingerprint in seen:
            duplicates.add(fingerprint)
        seen.add(fingerprint)
    return duplicates
