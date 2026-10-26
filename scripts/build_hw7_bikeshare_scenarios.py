"""HW7 Part 4: build the two Capital Bikeshare scenario CSVs from real public trip data.

Each monthly trip file is a zip on s3.amazonaws.com/capitalbikeshare-data. Only the
first 400 KB of each zip is downloaded (HTTP Range) and its deflate stream is
decompressed, which yields several thousand real trips spread over the month.
Rows are sampled with a fixed seed; every output row is an unmodified public trip.

Scenario = one hypothetical rider's trip history assembled from public trips:
  membership_wins   ~56 longer rides per month, Jan-Sep 2026 (frequent, some >45 min)
  payperuse_wins    ~8 short classic rides per month, Jan 2021 - Sep 2026 (occasional)

Outputs: tests/fixtures/hw7/bikeshare_<scenario>.csv and
reports/hw07/raw/bikeshare_<scenario>_trip_summary.json
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import struct
import sys
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "hw7"
RAW = ROOT / "reports" / "hw07" / "raw"
BASE_URL = "https://s3.amazonaws.com/capitalbikeshare-data/{month}-capitalbikeshare-tripdata.zip"
SEED = 36
RANGE_BYTES = 400_000


def months(start: str, end: str) -> list[str]:
    year, month = int(start[:4]), int(start[4:])
    out = []
    while f"{year}{month:02d}" <= end:
        out.append(f"{year}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


SCENARIOS = {
    "membership_wins": {
        "description": "Frequent rider: about 56 rides per 30 days, 8-75 minutes, classic and ebike.",
        "months": months("202601", "202609"),
        "per_month": 56,
        "keep": lambda row, minutes: 8 <= minutes <= 75,
    },
    "payperuse_wins": {
        "description": "Occasional rider: about 8 short classic rides per 30 days (3-10 minutes).",
        "months": months("202101", "202609"),
        "per_month": 8,
        "keep": lambda row, minutes: 3 <= minutes <= 10 and row["rideable_type"] in ("classic_bike", "docked_bike"),
    },
}


def fetch_month_rows(month: str) -> tuple[list[dict[str, str]], str]:
    url = BASE_URL.format(month=month)
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{RANGE_BYTES - 1}", "User-Agent": "s0036-hw7"})
    data = urllib.request.urlopen(request, timeout=60).read()
    signature, _, flags, method, *_rest = struct.unpack("<IHHHHHIIIHH", data[:30])
    name_len, extra_len = struct.unpack("<HH", data[26:30])
    name = data[30:30 + name_len].decode("utf-8", "ignore")
    if signature != 0x04034B50 or method != 8 or not name.endswith(".csv"):
        raise ValueError(f"{month}: unexpected zip entry {name!r} (method {method})")
    text = zlib.decompressobj(-15).decompress(data[30 + name_len + extra_len:]).decode("utf-8", "ignore")
    lines = text.splitlines()[:-1]  # the last line may be cut mid-row
    return list(csv.DictReader(io.StringIO("\n".join(lines)))), url


def minutes_between(started: str, ended: str) -> float:
    fmt = "%Y-%m-%d %H:%M:%S"
    return (datetime.strptime(ended[:19], fmt) - datetime.strptime(started[:19], fmt)).total_seconds() / 60


def build(name: str, spec: dict) -> None:
    rng = random.Random(f"{SEED}-{name}")
    selected, sources, header = [], [], None
    for month in spec["months"]:
        rows, url = fetch_month_rows(month)
        header = header or list(rows[0])
        candidates = []
        for row in rows:
            try:
                minutes = minutes_between(row["started_at"], row["ended_at"])
            except (KeyError, ValueError):
                continue
            if spec["keep"](row, minutes):
                candidates.append(row)
        picked = rng.sample(candidates, min(spec["per_month"], len(candidates)))
        selected.extend(sorted(picked, key=lambda r: r["started_at"]))
        sources.append({"month": month, "url": url, "rows_read": len(rows), "candidates": len(candidates),
                        "picked": len(picked)})
        print(f"  {name} {month}: read {len(rows)} rows, {len(candidates)} candidates, picked {len(picked)}",
              flush=True)

    selected.sort(key=lambda r: r["started_at"])
    out = FIXTURES / f"bikeshare_{name}.csv"
    with out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(selected)
    durations = [minutes_between(r["started_at"], r["ended_at"]) for r in selected]
    types: dict[str, int] = {}
    for r in selected:
        types[r["rideable_type"]] = types.get(r["rideable_type"], 0) + 1
    summary = {
        "scenario": name,
        "description": spec["description"],
        "csv": str(out.relative_to(ROOT)),
        "csv_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "rows": len(selected),
        "first_trip": selected[0]["started_at"],
        "last_trip": selected[-1]["started_at"],
        "rideable_types": types,
        "duration_minutes": {"mean": round(sum(durations) / len(durations), 2), "min": round(min(durations), 2),
                             "max": round(max(durations), 2),
                             "over_45": sum(d > 45 for d in durations)},
        "sampling": {"seed": f"{SEED}-{name}", "range_bytes_per_month": RANGE_BYTES,
                     "per_month": spec["per_month"], "months": len(spec["months"])},
        "source_files": sources,
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    (RAW / f"bikeshare_{name}_trip_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{name}: {len(selected)} rows -> {out.relative_to(ROOT)}  sha256={summary['csv_sha256'][:16]}...")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    targets = sys.argv[1:] or list(SCENARIOS)
    for name in targets:
        build(name, SCENARIOS[name])


if __name__ == "__main__":
    main()
