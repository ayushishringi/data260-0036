from datetime import datetime, timezone

from sqlalchemy import select

from backend.database import db_session_basede26
from backend.models import RelatedAdvisory, VulnerabilityReport


BENCHMARK_PREFIX = "hw4-n1-package-"
REPORT_COUNT = 5000
ADVISORY_COUNT = 200


def main() -> None:
    db = db_session_basede26()

    try:
        # Remove only older benchmark rows created by this script.
        old_reports = db.scalars(
            select(VulnerabilityReport).where(
                VulnerabilityReport.package_name.like(
                    f"{BENCHMARK_PREFIX}%"
                )
            )
        ).all()

        for report in old_reports:
            db.delete(report)

        db.commit()

        # Create 5,000 main vulnerability reports.
        reports = []

        for index in range(REPORT_COUNT):
            reports.append(
                VulnerabilityReport(
                    report_code=f"VULN-0036-BENCH-{index:04d}",
                    package_name=f"{BENCHMARK_PREFIX}{index}",
                    affected_version="< 1.0.0",
                    submitter_email="benchmark@example.com",
                    description=(
                        "Benchmark vulnerability description for "
                        "measuring SQL query performance."
                    ),
                    severity="medium",
                    agreed_to_terms=True,
                    submission_date=datetime.now(
                        timezone.utc
                    ).replace(tzinfo=None),
                )
            )

        db.add_all(reports)
        db.flush()

        # Create 200 related advisories for the first 200 reports.
        advisories = []

        for index in range(ADVISORY_COUNT):
            advisories.append(
                RelatedAdvisory(
                    report_id=reports[index].id,
                    advisory_text=(
                        f"Benchmark advisory text for report {index}."
                    ),
                )
            )

        db.add_all(advisories)
        db.commit()

        print(
            f"Seeded {REPORT_COUNT} vulnerability reports "
            f"and {ADVISORY_COUNT} related advisories."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
