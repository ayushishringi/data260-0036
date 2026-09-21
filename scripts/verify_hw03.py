import json
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED_FILES = [
    "backend/auth.py",
    "backend/main.py",
    "questions.yaml",
    "src/retrieval.py",
    "scripts/run_hw3_retrieval.py",
    "corpus/SOURCES.md",
    "corpus/CORPUS_MANIFEST.json",
    "corpus/github_reviewed_advisories_snapshot.txt",
    "reports/hw03/RUN_LOG.txt",
    "reports/hw03/METRICS.md",
    "reports/hw03/AI_USE.md",
    "reports/hw03/raw/retrieval_outputs.json",
    "reports/hw03/raw/metrics.json",
]


def check_files() -> dict:
    return {
        path: (ROOT / path).exists()
        for path in REQUIRED_FILES
    }


def check_corpus() -> dict:
    corpus_file = (
        ROOT
        / "corpus"
        / "github_reviewed_advisories_snapshot.txt"
    )

    size_bytes = corpus_file.stat().st_size

    return {
        "size_bytes": size_bytes,
        "minimum_required_bytes": 200_000,
        "passed": size_bytes >= 200_000,
    }


def check_questions() -> dict:
    questions_file = ROOT / "questions.yaml"
    data = yaml.safe_load(
        questions_file.read_text(encoding="utf-8")
    )

    questions = data.get("questions", [])

    return {
        "count": len(questions),
        "expected_count": 5,
        "passed": len(questions) == 5,
    }


def check_retrieval_outputs() -> dict:
    output_file = (
        ROOT
        / "reports"
        / "hw03"
        / "raw"
        / "retrieval_outputs.json"
    )

    metrics_file = (
        ROOT
        / "reports"
        / "hw03"
        / "raw"
        / "metrics.json"
    )

    outputs = json.loads(
        output_file.read_text(encoding="utf-8")
    )

    metrics = json.loads(
        metrics_file.read_text(encoding="utf-8")
    )

    techniques = {
        "token",
        "semantic",
        "sentence_window",
    }

    output_techniques = set(
        outputs[0]["results"].keys()
    )

    return {
        "questions_in_output": len(outputs),
        "required_techniques": sorted(techniques),
        "output_techniques": sorted(output_techniques),
        "metrics_techniques": sorted(metrics.keys()),
        "passed": (
            len(outputs) == 5
            and output_techniques == techniques
            and set(metrics.keys()) == techniques
        ),
    }


def check_authentication() -> dict:
    from backend.auth import router
    from backend.main import app

    router_paths = [
        route.path
        for route in router.routes
    ]

    middleware_names = [
        middleware.cls.__name__
        for middleware in app.user_middleware
    ]

    required_paths = {
        "/",
        "/login",
        "/dashboard",
        "/logout",
    }

    return {
        "router_paths": router_paths,
        "session_middleware_present": (
            "SessionMiddleware" in middleware_names
        ),
        "required_router_paths_present": (
            required_paths.issubset(set(router_paths))
        ),
        "passed": (
            "SessionMiddleware" in middleware_names
            and required_paths.issubset(set(router_paths))
        ),
    }


def main():
    file_checks = check_files()

    checks = {
        "required_files": file_checks,
        "all_required_files_present": all(
            file_checks.values()
        ),
        "corpus": check_corpus(),
        "questions": check_questions(),
        "retrieval_outputs": check_retrieval_outputs(),
        "authentication": check_authentication(),
    }

    passed = (
        checks["all_required_files_present"]
        and checks["corpus"]["passed"]
        and checks["questions"]["passed"]
        and checks["retrieval_outputs"]["passed"]
        and checks["authentication"]["passed"]
    )

    result = {
        "passed": passed,
        "homework": "DATA-260 HW3",
        "SID4": "0036",
        "PORT_BASE": 8036,
        "DOMAIN_ID": 4,
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "checks": checks,
    }

    output_file = (
        ROOT
        / "reports"
        / "hw03"
        / "verification.json"
    )

    output_file.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, indent=2))
    print(f"\nSaved verification to: {output_file}")


if __name__ == "__main__":
    main()