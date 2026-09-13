from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = Path(__file__).resolve().parent / "records.json"

Severity = Literal["critical", "high", "medium", "low"]


class VulnerabilityReportInput(BaseModel):
    packageName: str = Field(min_length=1)
    affectedVersion: str = Field(min_length=1)
    submitterEmail: str = Field(min_length=3)
    description: str = Field(min_length=26)
    severity: Severity
    agreedToTerms: bool

    @field_validator(
        "packageName",
        "affectedVersion",
        "submitterEmail",
        "description",
    )
    @classmethod
    def fields_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be blank.")

        return value

    @field_validator("agreedToTerms")
    @classmethod
    def terms_must_be_accepted(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Terms must be accepted.")

        return value


class VulnerabilityReport(VulnerabilityReportInput):
    id: int
    submissionDate: str


app = FastAPI(title="DATA-260 HW2 Vulnerability Reports")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def default_records() -> list[dict]:
    return [
        {
            "id": 1,
            "packageName": "example-http-client",
            "affectedVersion": "< 2.4.1",
            "submitterEmail": "reporter@example.edu",
            "description": (
                "TLS certificate hostname verification is skipped when a "
                "custom proxy URL is set, allowing interception."
            ),
            "severity": "high",
            "agreedToTerms": True,
            "submissionDate": "2026-09-01T12:00:00+00:00",
        },
        {
            "id": 2,
            "packageName": "lodash",
            "affectedVersion": "< 4.17.21",
            "submitterEmail": "security@example.edu",
            "description": (
                "A vulnerable package version permits prototype pollution "
                "through specially crafted object properties."
            ),
            "severity": "critical",
            "agreedToTerms": True,
            "submissionDate": "2026-09-02T12:00:00+00:00",
        },
    ]


def load_records() -> list[dict]:
    if not DATA_FILE.exists():
        records = default_records()
        save_records(records)
        return records

    return json.loads(DATA_FILE.read_text())


def save_records(records: list[dict]) -> None:
    DATA_FILE.write_text(json.dumps(records, indent=2) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "ok", "port": 8036}


@app.get("/api/reports", response_model=list[VulnerabilityReport])
def list_reports(
    search: str | None = Query(default=None),
) -> list[dict]:
    records = load_records()

    if not search or not search.strip():
        return records

    search_text = search.strip().lower()

    return [
        record
        for record in records
        if search_text in record["packageName"].lower()
        or search_text in record["affectedVersion"].lower()
    ]


@app.post("/api/reports", response_model=VulnerabilityReport, status_code=201)
def create_report(report: VulnerabilityReportInput) -> dict:
    records = load_records()
    next_id = max((record["id"] for record in records), default=0) + 1

    new_record = {
        "id": next_id,
        **report.model_dump(),
        "submissionDate": now_iso(),
    }

    records.append(new_record)
    save_records(records)

    return new_record


@app.put("/api/reports/1", response_model=VulnerabilityReport)
def update_first_report(report: VulnerabilityReportInput) -> dict:
    records = load_records()

    for index, record in enumerate(records):
        if record["id"] == 1:
            updated_record = {
                "id": 1,
                **report.model_dump(),
                "submissionDate": record["submissionDate"],
            }

            records[index] = updated_record
            save_records(records)

            return updated_record

    raise HTTPException(
        status_code=404,
        detail="Record with ID 1 was not found.",
    )


@app.delete("/api/reports/highest", response_model=VulnerabilityReport)
def delete_highest_report() -> dict:
    records = load_records()

    if not records:
        raise HTTPException(
            status_code=404,
            detail="No records exist.",
        )

    highest_record = max(records, key=lambda record: record["id"])
    records.remove(highest_record)
    save_records(records)

    return highest_record


app.mount(
    "/",
    StaticFiles(directory=ROOT, html=True),
    name="static",
)