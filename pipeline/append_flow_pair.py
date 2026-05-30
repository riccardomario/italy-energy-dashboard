"""
One-off: fetch a single border pair (both directions) for the full history and
append it to data/flows.parquet, de-duplicating on (timestamp, from_zone, to_zone).

Use when a border was missing/wrong in the main backfill, to avoid re-running
the whole flow stage.

Example:
    py pipeline\append_flow_pair.py IT_CALA IT_SICI
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.fetch_entsoe import fetch_flow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FLOW_PARQUET = ROOT / "data" / "flows.parquet"
START = "2016-01-01"


def main():
    if len(sys.argv) != 3:
        print("usage: py pipeline\\append_flow_pair.py <ZONE_A> <ZONE_B>")
        sys.exit(1)
    a, b = sys.argv[1], sys.argv[2]
    end = pd.Timestamp.utcnow().normalize().strftime("%Y-%m-%d")
    print(f"Fetching {a} <-> {b}  ({START} -> {end})")

    new_parts = []
    for from_zone, to_zone in [(a, b), (b, a)]:
        print(f"\n  {from_zone} -> {to_zone}")
        df = fetch_flow(from_zone, to_zone, START, end)
        print(f"    -> {len(df):,} rows")
        if len(df) > 0:
            new_parts.append(df)
    if not new_parts:
        print("No data fetched; nothing to append.")
        return
    new = pd.concat(new_parts, ignore_index=True)

    if FLOW_PARQUET.exists():
        existing = pd.read_parquet(FLOW_PARQUET)
        before = len(existing)
        combined = pd.concat([existing, new], ignore_index=True)
    else:
        before = 0
        combined = new

    combined = combined.drop_duplicates(
        subset=["timestamp_utc", "from_zone", "to_zone"], keep="last"
    ).sort_values(["from_zone", "to_zone", "timestamp_utc"]).reset_index(drop=True)

    combined.to_parquet(FLOW_PARQUET, index=False)
    print(f"\n  flows.parquet: {before:,} -> {len(combined):,} rows "
          f"({FLOW_PARQUET.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
