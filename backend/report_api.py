from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session , selectinload

from backend.database import get_db
from backend.models import User, VulnerabilityReport
from backend.schemas import ReportInput
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
            selectinload(VulnerabilityReport.advisories)
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
    report = db.get(VulnerabilityReport, report_id)

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

    db.commit()
    db.refresh(report)

    return report_to_dict(report)


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