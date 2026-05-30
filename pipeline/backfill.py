"""
One-shot backfill: fetch all historical data 2016-01-01 -> today and write
three parquet files in ./data/.

Run with:
    py pipeline\backfill.py

Resumable: if a parquet file already exists, that section is skipped.
Force a re-download with --force.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Make `pipeline` importable when launched directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.fetch_entsoe import fetch_flow, fetch_generation, fetch_load  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

START = "2016-01-01"
# END is "today 00:00 UTC" (computed at run time)

# 7 Italian bidding zones for load and generation
BIDDING_ZONES = [
    "IT_NORD", "IT_CNOR", "IT_CSUD",
    "IT_SUD", "IT_SICI", "IT_SARD", "IT_CALA",
]

# External Italian borders (entsoe-py expects standard ENTSO-e zone codes).
# Each pair is queried in BOTH directions and saved with explicit sign.
EXTERNAL_BORDERS = [
    ("IT_NORD", "FR"),
    ("IT_NORD", "CH"),
    ("IT_NORD", "AT"),
    ("IT_NORD", "SI"),
    ("IT_BRNN", "GR"),   # Italy-Greece HVDC (virtual zone Brindisi); data 2016-2019
    # ME (Montenegro) and MT (Malta) omitted: ENTSO-e returns "Invalid country
    # code" for these under the available zone codes — no data to fetch.
]

# Internal Italian zonal flows
INTERNAL_BORDERS = [
    ("IT_NORD", "IT_CNOR"),
    ("IT_CNOR", "IT_CSUD"),
    ("IT_CSUD", "IT_SUD"),
    ("IT_CSUD", "IT_SARD"),
    ("IT_SUD",  "IT_CALA"),
    ("IT_CALA", "IT_SICI"),  # Sicily-mainland link; published 2021+ (IT_CALA zone reform)
]

ALL_BORDERS = EXTERNAL_BORDERS + INTERNAL_BORDERS

LOAD_PARQUET = DATA_DIR / "load.parquet"
GEN_PARQUET = DATA_DIR / "generation.parquet"
FLOW_PARQUET = DATA_DIR / "flows.parquet"
STATUS_JSON = DATA_DIR / "last_update.json"


# ---------------------------------------------------------------------------
# Backfill stages
# ---------------------------------------------------------------------------

PARTIAL_DIR = DATA_DIR / "_partials"


def _partial_path(stage: str, key: str) -> Path:
    safe = key.replace("/", "_").replace(" ", "_")
    return PARTIAL_DIR / f"{stage}__{safe}.parquet"


def _consolidate_partials(stage: str, final_path: Path):
    """Read all per-key partials for a stage, concat, write final, clean up."""
    files = sorted(PARTIAL_DIR.glob(f"{stage}__*.parquet"))
    if not files:
        print(f"  no partials for {stage}; skipping write")
        return
    dfs = [pd.read_parquet(f) for f in files]
    out = pd.concat(dfs, ignore_index=True)
    out.to_parquet(final_path, index=False)
    print(f"\n  wrote {final_path}  ({len(out):,} rows, "
          f"{final_path.stat().st_size / 1e6:.1f} MB)")
    for f in files:
        f.unlink()


def backfill_load(start, end):
    print(f"\n=== LOAD ({len(BIDDING_ZONES)} zones) ===")
    PARTIAL_DIR.mkdir(exist_ok=True)
    for zone in BIDDING_ZONES:
        partial = _partial_path("load", zone)
        if partial.exists():
            print(f"\n  zone: {zone}  [skip, partial exists]")
            continue
        print(f"\n  zone: {zone}")
        df = fetch_load(zone, start, end)
        print(f"    -> {len(df):,} rows")
        if len(df) > 0:
            df.to_parquet(partial, index=False)
    _consolidate_partials("load", LOAD_PARQUET)


def backfill_generation(start, end):
    print(f"\n=== GENERATION ({len(BIDDING_ZONES)} zones) ===")
    PARTIAL_DIR.mkdir(exist_ok=True)
    for zone in BIDDING_ZONES:
        partial = _partial_path("gen", zone)
        if partial.exists():
            print(f"\n  zone: {zone}  [skip, partial exists]")
            continue
        print(f"\n  zone: {zone}")
        df = fetch_generation(zone, start, end)
        print(f"    -> {len(df):,} rows")
        if len(df) > 0:
            df.to_parquet(partial, index=False)
    _consolidate_partials("gen", GEN_PARQUET)


def backfill_flows(start, end):
    print(f"\n=== FLOWS ({len(ALL_BORDERS)} borders, both directions) ===")
    PARTIAL_DIR.mkdir(exist_ok=True)
    for a, b in ALL_BORDERS:
        for from_zone, to_zone in [(a, b), (b, a)]:
            key = f"{from_zone}__to__{to_zone}"
            partial = _partial_path("flow", key)
            if partial.exists():
                print(f"\n  {from_zone} -> {to_zone}  [skip, partial exists]")
                continue
            print(f"\n  {from_zone} -> {to_zone}")
            df = fetch_flow(from_zone, to_zone, start, end)
            print(f"    -> {len(df):,} rows")
            if len(df) > 0:
                df.to_parquet(partial, index=False)
    _consolidate_partials("flow", FLOW_PARQUET)


def write_status(start, end):
    from pipeline.update import compute_data_end_utc
    data_end = compute_data_end_utc() or str(pd.Timestamp(end).date())
    status = {
        "last_run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_run_status": "success",
        "data_start": str(pd.Timestamp(start).date()),
        "data_end": data_end,
        "files": {
            "load": str(LOAD_PARQUET.relative_to(ROOT).as_posix()),
            "generation": str(GEN_PARQUET.relative_to(ROOT).as_posix()),
            "flows": str(FLOW_PARQUET.relative_to(ROOT).as_posix()),
        },
    }
    with open(STATUS_JSON, "w") as f:
        json.dump(status, f, indent=2)
    print(f"\n  wrote {STATUS_JSON}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Backfill ENTSO-e data 2016 -> today.")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if parquet files already exist")
    ap.add_argument("--only", choices=["load", "generation", "flows"], default=None,
                    help="Run only one stage")
    ap.add_argument("--start", default=START, help=f"Start date (default {START})")
    ap.add_argument("--end", default=None,
                    help="End date (default: today 00:00 UTC)")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    start = args.start
    end = args.end or pd.Timestamp.utcnow().normalize().strftime("%Y-%m-%d")

    print(f"Backfill window: {start} -> {end}")
    print(f"Output dir:      {DATA_DIR}")

    def should_run(stage_name: str, path: Path) -> bool:
        if args.only and args.only != stage_name:
            return False
        if path.exists() and not args.force:
            print(f"\n[skip {stage_name}] {path.name} already exists "
                  f"(use --force to overwrite)")
            return False
        return True

    t0 = datetime.now()
    if should_run("load", LOAD_PARQUET):
        backfill_load(start, end)
    if should_run("generation", GEN_PARQUET):
        backfill_generation(start, end)
    if should_run("flows", FLOW_PARQUET):
        backfill_flows(start, end)

    write_status(start, end)
    elapsed = datetime.now() - t0
    print(f"\nDONE in {elapsed}.")


if __name__ == "__main__":
    main()
