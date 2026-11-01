"""HW8 Part 1 domain logic: CREATE_REPORT / GET_REPORT for the VulnerabilityReport entity.

Pure functions over a plain Python dict, so the Kafka worker stays thin and this is unit-testable.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

CREATE_OPERATION = "CREATE_REPORT"
GET_OPERATION = "GET_REPORT"
SEVERITIES = ("critical", "high", "medium", "low")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
REQUIRED_FIELDS = ("package_name", "affected_version", "severity", "description", "submitter_email")
REQUEST_KEYS = ("correlation_id", "reply_to", "operation", "data")


def validate_report(data: Any) -> tuple[dict[str, str] | None, str | None]:
    """Return (clean_fields, None) or (None, error) for CREATE_REPORT data."""

    if not isinstance(data, dict):
        return None, "data must be a JSON object"
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        return None, f"Missing required field(s): {', '.join(missing)}"
    unknown = sorted(set(data) - set(REQUIRED_FIELDS))
    if unknown:
        return None, f"Unknown field(s): {', '.join(unknown)}"
    clean: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        value = data[field]
        if not isinstance(value, str) or not value.strip():
            return None, f"Field '{field}' must be a non-empty string"
        clean[field] = value.strip()
    if len(clean["package_name"]) > 100:
        return None, "Field 'package_name' must be at most 100 characters"
    if clean["severity"].lower() not in SEVERITIES:
        return None, f"Field 'severity' must be one of: {', '.join(SEVERITIES)}"
    clean["severity"] = clean["severity"].lower()
    if len(clean["description"]) < 20:
        return None, "Field 'description' must be at least 20 characters"
    if not EMAIL_RE.match(clean["submitter_email"]):
        return None, "Field 'submitter_email' must be a valid email address"
    return clean, None


def handle_request(message: Any, store: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Process one request message and return the response (always echoing correlation_id)."""

    correlation_id = message.get("correlation_id") if isinstance(message, dict) else None
    base = {"correlation_id": correlation_id}
    if not isinstance(message, dict):
        return {**base, "success": False, "error": "Request must be a JSON object"}
    missing = [k for k in REQUEST_KEYS if k not in message]
    if missing:
        return {**base, "success": False, "error": f"Malformed request: missing {', '.join(missing)}"}
    operation, data = message["operation"], message["data"]
    base["operation"] = operation

    if operation == CREATE_OPERATION:
        clean, error = validate_report(data)
        if error:
            return {**base, "success": False, "error": error}
        report_id = str(uuid.uuid4())
        store[report_id] = {"report_id": report_id, **clean}
        return {**base, "success": True, "report_id": report_id, "message": "Report created"}

    if operation == GET_OPERATION:
        report_id = data.get("report_id") if isinstance(data, dict) else None
        if not isinstance(report_id, str) or not report_id.strip():
            return {**base, "success": False, "error": "Field 'report_id' is required"}
        report = store.get(report_id.strip())
        if report is None:
            return {**base, "success": False, "error": "Report not found"}
        return {**base, "success": True, "report": dict(report)}

    return {**base, "success": False, "error": "Unknown operation"}
