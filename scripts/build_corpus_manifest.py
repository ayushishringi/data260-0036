import hashlib
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "corpus"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def file_record(path: Path) -> dict:
    return {
        "filename": str(path.relative_to(ROOT)),
        "byte_size": path.stat().st_size,
        "sha256": file_hash(path),
    }


def main():
    snapshot = (
        CORPUS_DIR
        / "github_reviewed_advisories_snapshot.txt"
    )

    sources = CORPUS_DIR / "SOURCES.md"

    manifest = {
        "domain_id": 4,
        "domain": "Open-source package vulnerabilities",
        "source_name": "GitHub Advisory Database",
        "source_repository": (
            "https://github.com/github/advisory-database"
        ),
        "source_section": "advisories/github-reviewed",
        "access_date": str(date.today()),
        "retrieval_model": (
            "sentence-transformers/all-MiniLM-L6-v2"
        ),
        "records_in_snapshot": 500,
        "records_available_in_checkout": 938,
        "minimum_required_size_bytes": 200000,
        "files": [
            file_record(snapshot),
            file_record(sources),
        ],
    }

    output_file = CORPUS_DIR / "CORPUS_MANIFEST.json"

    output_file.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(manifest, indent=2))
    print(f"\nSaved: {output_file}")


if __name__ == "__main__":
    main()