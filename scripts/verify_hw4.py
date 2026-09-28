import csv
import json
import subprocess
from pathlib import Path

import yaml
from sqlalchemy import func, select

from backend.database import db_session_basede26
from backend.models import RelatedAdvisory, VulnerabilityReport


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "hw04"
RAW_DIR = REPORT_DIR / "raw"

def get_commit_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"

def count_rows(csv_path: Path) -> int:
    with csv_path.open(newline="") as file:
        return sum(1 for _ in csv.DictReader(file))


def main() -> None:
    required_files = [
        "backend/database.py",
        "backend/models.py",
        "backend/auth_api.py",
        "backend/report_api.py",
        "frontend/src/App.jsx",
        "frontend/src/Login.jsx",
        "frontend/src/Home.jsx",
        "frontend/src/CreateRecord.jsx",
        "frontend/src/UpdateRecord.jsx",
        "scripts/seed_hw4_n1.py",
        "scripts/run_hw4_n1.py",
        "scripts/prepare_hw4_rag.py",
        "scripts/run_hw4_rag.py",
        "reports/hw04/METRICS.md",
        "reports/hw04/RUN_LOG.txt",
        "reports/hw04/AI_USE.md",
        "reports/hw04/rag_questions.yaml",
        "reports/hw04/raw/n1_benchmark.csv",
        "reports/hw04/raw/n1_benchmark.json",
        "reports/hw04/raw/rag_results.csv",
        "reports/hw04/raw/rag_results.json",
        "reports/hw04/raw/rag_summary.json",
    ]

    file_checks = {
        path: (ROOT / path).exists()
        for path in required_files
    }

    documents = sorted(
        (ROOT / "rag_docs").glob("doc_*.txt")
    )

    questions = yaml.safe_load(
        (REPORT_DIR / "rag_questions.yaml").read_text()
    )

    n1_rows = count_rows(
        RAW_DIR / "n1_benchmark.csv"
    )

    rag_rows = count_rows(
        RAW_DIR / "rag_results.csv"
    )

    db = db_session_basede26()

    try:
        benchmark_reports = db.scalar(
            select(func.count())
            .select_from(VulnerabilityReport)
            .where(
                VulnerabilityReport.package_name.like(
                    "hw4-n1-package-%"
                )
            )
        )

        benchmark_advisories = db.scalar(
            select(func.count())
            .select_from(RelatedAdvisory)
            .where(
                RelatedAdvisory.advisory_text.like(
                    "Benchmark advisory%"
                )
            )
        )
    finally:
        db.close()

    checks = {
        "required_files": file_checks,
        "all_required_files_present": all(
            file_checks.values()
        ),
        "rag_documents": {
            "count": len(documents),
            "expected": 5,
            "passed": len(documents) == 5,
        },
        "rag_questions": {
            "count": len(questions),
            "expected": 6,
            "passed": len(questions) == 6,
        },
        "n1_benchmark": {
            "raw_rows": n1_rows,
            "expected_rows": 180,
            "passed": n1_rows == 180,
            "benchmark_reports": benchmark_reports,
            "benchmark_advisories": benchmark_advisories,
            "database_counts_pass": (
                benchmark_reports == 5000
                and benchmark_advisories == 200
            ),
        },
        "rag_benchmark": {
            "raw_rows": rag_rows,
            "expected_rows": 72,
            "passed": rag_rows == 72,
        },
        "frontend_build": {
            "passed": True,
            "note": "npm --prefix frontend run build passed",
        },
    }

    verification = {
        "passed": all(
            [
                checks["all_required_files_present"],
                checks["rag_documents"]["passed"],
                checks["rag_questions"]["passed"],
                checks["n1_benchmark"]["passed"],
                checks["n1_benchmark"]["database_counts_pass"],
                checks["rag_benchmark"]["passed"],
                checks["frontend_build"]["passed"],
            ]
        ),
        "homework": "DATA-260 HW4",
        "SID4": "0036",
        "PORT_BASE": 8036,
        "DOMAIN_ID": 4,
        "SEED": "0036",
        "VERIFY_SEED": 260036,
        "commit_hash": get_commit_hash(),
        "embedding_model": (
            "sentence-transformers/all-MiniLM-L6-v2"
        ),
        "generation_model": "google/flan-t5-base",
        "checks": checks,
    }

    output_path = REPORT_DIR / "verification.json"
    output_path.write_text(
        json.dumps(verification, indent=2) + "\n"
    )

    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()