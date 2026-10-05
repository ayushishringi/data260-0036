from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.database import get_db
from backend.models import Advisory, User, VulnerabilityReport
from backend.schemas import AdvisoryInput, ReportInput
from backend.security import get_current_user


router = APIRouter(
    prefix="/api/reports",
    tags=["reports"],
)


def report_to_dict(report: VulnerabilityReport) -> dict:
    return {
        "id": report.id,
        "packageName": report.package_name,
        "affectedVersion": report.affected_version,
        "submitterEmail": report.submitter_email,
        "description": report.description,
        "severity": report.severity,
        "agreedToTerms": report.agreed_to_terms,
        "submissionDate": report.submission_date.isoformat(),
        "createdAt": report.created_at.isoformat(),
        "updatedAt": report.updated_at.isoformat(),
        "advisoryId": report.advisory_id,
        "availableCount": report.available_count,
        "advisory": (
            {
                "id": report.advisory.id,
                "name": report.advisory.name,
                "publisher": report.advisory.publisher,
                "advisoryCode": report.advisory.advisory_code,
            }
            if report.advisory else None
        ),
        "related": [
            {
                "id": advisory.id,
                "text": advisory.advisory_text,
            }
            for advisory in report.advisories
        ],
    }


@router.get("")
def list_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    reports = db.scalars(
        select(VulnerabilityReport)
        .options(
            selectinload(VulnerabilityReport.advisories),
            selectinload(VulnerabilityReport.advisory),
        )
    .order_by(VulnerabilityReport.id)
    ).all()
    

    return [report_to_dict(report) for report in reports]


@router.get("/{report_id}")
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    report = db.scalar(
        select(VulnerabilityReport)
        .options(
            selectinload(VulnerabilityReport.advisories),
            selectinload(VulnerabilityReport.advisory),
        )
        .where(VulnerabilityReport.id == report_id)
    )

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found",
        )

    return report_to_dict(report)


@router.post("", status_code=201)
def create_report(
    payload: ReportInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    report = VulnerabilityReport(
        package_name=payload.packageName,
        affected_version=payload.affectedVersion,
        submitter_email=str(payload.submitterEmail),
        description=payload.description,
        severity=payload.severity,
        agreed_to_terms=payload.agreedToTerms,
        submission_date=datetime.now(
            timezone.utc
        ).replace(tzinfo=None),
        advisory_id=payload.advisoryId,
        available_count=payload.availableCount,
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    return report_to_dict(report)


@router.put("/{report_id}")
def update_report(
    report_id: int,
    payload: ReportInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    report = db.get(VulnerabilityReport, report_id)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found",
        )

    report.package_name = payload.packageName
    report.affected_version = payload.affectedVersion
    report.submitter_email = str(payload.submitterEmail)
    report.description = payload.description
    report.severity = payload.severity
    report.agreed_to_terms = payload.agreedToTerms
    report.advisory_id = payload.advisoryId
    report.available_count = payload.availableCount

    db.commit()
    updated_report = db.scalar(
        select(VulnerabilityReport)
        .options(
            selectinload(VulnerabilityReport.advisories),
            selectinload(VulnerabilityReport.advisory),
        )
        .where(VulnerabilityReport.id == report_id)
    )
    return report_to_dict(updated_report)


def advisory_to_dict(advisory: Advisory) -> dict:
    return {
        "id": advisory.id,
        "name": advisory.name,
        "publisher": advisory.publisher,
        "advisoryCode": advisory.advisory_code,
        "createdAt": advisory.created_at.isoformat(),
        "updatedAt": advisory.updated_at.isoformat(),
    }


@router.get("/advisories")
def list_advisories(
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    limit = min(max(limit, 1), 100)
    advisories = db.scalars(
        select(Advisory).order_by(Advisory.id).offset(max(offset, 0)).limit(limit)
    ).all()
    return [advisory_to_dict(item) for item in advisories]


@router.get("/advisories/{advisory_id}")
def get_advisory(
    advisory_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    advisory = db.get(Advisory, advisory_id)
    if advisory is None:
        raise HTTPException(status_code=404, detail="Advisory not found")
    return advisory_to_dict(advisory)


@router.post("/advisories", status_code=201)
def create_advisory(
    payload: AdvisoryInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if db.scalar(select(Advisory).where(Advisory.advisory_code == payload.advisoryCode)):
        raise HTTPException(status_code=409, detail="Advisory code already exists")
    advisory = Advisory(
        name=payload.name.strip(), publisher=payload.publisher.strip(),
        advisory_code=payload.advisoryCode.strip(),
    )
    db.add(advisory)
    db.commit()
    db.refresh(advisory)
    return advisory_to_dict(advisory)


@router.put("/advisories/{advisory_id}")
def update_advisory(
    advisory_id: int, payload: AdvisoryInput,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
) -> dict:
    advisory = db.get(Advisory, advisory_id)
    if advisory is None:
        raise HTTPException(status_code=404, detail="Advisory not found")
    duplicate = db.scalar(select(Advisory).where(
        Advisory.advisory_code == payload.advisoryCode, Advisory.id != advisory_id
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="Advisory code already exists")
    advisory.name, advisory.publisher, advisory.advisory_code = (
        payload.name.strip(), payload.publisher.strip(), payload.advisoryCode.strip()
    )
    db.commit()
    db.refresh(advisory)
    return advisory_to_dict(advisory)


@router.delete("/advisories/{advisory_id}", status_code=204)
def delete_advisory(
    advisory_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    advisory = db.get(Advisory, advisory_id)
    if advisory is None:
        raise HTTPException(status_code=404, detail="Advisory not found")
    if db.scalar(select(VulnerabilityReport.id).where(VulnerabilityReport.advisory_id == advisory_id)):
        raise HTTPException(status_code=409, detail="Cannot delete advisory with linked reports")
    db.delete(advisory)
    db.commit()


@router.get("/advisories/{advisory_id}/reports")
def reports_for_advisory(
    advisory_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    if db.get(Advisory, advisory_id) is None:
        raise HTTPException(status_code=404, detail="Advisory not found")
    reports = db.scalars(select(VulnerabilityReport).where(
        VulnerabilityReport.advisory_id == advisory_id
    ).order_by(VulnerabilityReport.id)).all()
    return [report_to_dict(report) for report in reports]


@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    report = db.get(VulnerabilityReport, report_id)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found",
        )

    db.delete(report)
    db.commit()


# Register static advisory paths before the generic /{report_id} paths.
# Without this, FastAPI attempts to parse the word "advisories" as an integer.
router.routes.sort(key=lambda route: "{report_id}" in getattr(route, "path", ""))
