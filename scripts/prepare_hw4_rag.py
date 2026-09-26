import hashlib
import json
import re
from pathlib import Path


SOURCE_PATH = Path(
    "corpus/github_reviewed_advisories_snapshot.txt"
)
OUTPUT_DIR = Path("rag_docs")
MANIFEST_PATH = Path(
    "reports/hw04/rag_corpus_manifest.json"
)


def main() -> None:
    text = SOURCE_PATH.read_text()

    records = re.split(
        r"\n(?=--- SOURCE:)",
        text,
    )

    records = [
        record.strip()
        for record in records
        if record.strip().startswith("--- SOURCE:")
    ]

    selected_records = records[:5]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source_file": str(SOURCE_PATH),
        "document_count": len(selected_records),
        "documents": [],
    }

    for index, record in enumerate(selected_records, start=1):
        output_path = OUTPUT_DIR / f"doc_{index:02d}.txt"
        output_path.write_text(record + "\n")

        file_bytes = output_path.read_bytes()

        manifest["documents"].append(
            {
                "document_id": f"doc_{index:02d}",
                "filename": str(output_path),
                "bytes": len(file_bytes),
                "sha256": hashlib.sha256(
                    file_bytes
                ).hexdigest(),
            }
        )

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n"
    )

    print(
        f"Created {len(selected_records)} documents "
        f"in {OUTPUT_DIR}"
    )
    print(f"Wrote manifest to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()