from models import EntryPayload
from ripley_client import ValidationError, duplicate_fingerprints, normalize_entry


def independent_entry(**overrides):
    data = {
        "date": "2026-08-03",
        "start_time": "09:00",
        "end_time": "11:00",
        "supervisor_id": "133282",
        "organization_id": "78119",
        "hour_type": "Independent",
        "independent_unrestricted": 2,
        "description": "Test entry",
    }
    data.update(overrides)
    return EntryPayload(**data)


def test_normalization():
    result = normalize_entry(independent_entry())
    assert result.date_display == "08/03/2026"
    assert result.start_parts == ("9", "00", "am")
    assert result.end_parts == ("11", "00", "am")
    assert result.duration == 2


def test_allocation_must_match():
    try:
        normalize_entry(independent_entry(independent_unrestricted=1))
    except ValidationError:
        return
    raise AssertionError("Expected allocation validation failure")


def test_duplicate_detection():
    item = independent_entry()
    assert len(duplicate_fingerprints([item, item])) == 1
