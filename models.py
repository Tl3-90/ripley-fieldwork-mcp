from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


HourType = Literal["Independent", "Supervised"]
ContactType = Literal["Contact", "Observation"]
FormatType = Literal["In-Person", "Online", "Phone Call"]


class EntryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(description="YYYY-MM-DD or MM/DD/YYYY")
    start_time: str = Field(description="24-hour HH:MM or 12-hour time such as 4:30 PM")
    end_time: str = Field(description="24-hour HH:MM or 12-hour time such as 5:30 PM")
    supervisor_id: str
    organization_id: str
    hour_type: HourType
    independent_restricted: float = Field(default=0, ge=0)
    independent_unrestricted: float = Field(default=0, ge=0)
    supervised_individual_restricted: float = Field(default=0, ge=0)
    supervised_individual_unrestricted: float = Field(default=0, ge=0)
    supervised_group_unrestricted: float = Field(default=0, ge=0)
    observation_time: float = Field(default=0, ge=0)
    contact_type: ContactType | None = None
    format_type: FormatType | None = None
    description: str = ""


class BulkEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[EntryPayload] = Field(min_length=1, max_length=500)
    dry_run: bool = True
    stop_on_error: bool = True
    allow_duplicates: bool = False


class UpdateEntryRequest(EntryPayload):
    pass
