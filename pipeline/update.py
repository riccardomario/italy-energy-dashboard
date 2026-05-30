"""
Incremental daily update: fetch the last N days from ENTSO-e and merge into the
existing parquet stores, overwriting any revised values.

Run with:
    py pipeline/update.py                 # default 14-day lookback
    py pipeline/update.py --lookback 60   # monthly deep refresh

Designed to run both locally (manual refresh) and on GitHub Actions (cron).
De-duplicates keeping the newest value, so provisional figures get replaced by
finals. Reports how many already-stored rows changed (revisions).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.backfill import (  # noqa: E402
    ALL_BORDERS, BIDDING_ZONES, DATA_DIR,
    FLOW_PARQUET, GEN_PARQUET, LOAD_PARQUET, STATUS_JSON,
)
from pipeline.fetch_entsoe import (  # noqa: E402
    fetch_flow, fetch_generation, fetch_load,
)


def _merge(existing: pd.DataFrame, new: pd.DataFrame, key_cols: list[str],
           value_cols: list[str]) -> tuple[pd.DataFrame, int]:
    """Merge new rows into existing, newest value wins. Returns (combined,
    n_revised) where n_revised counts already-stored rows whose value changed.
    """
    if existing.empty:
        return new.sort_values(key_cols).reset_index(drop=True), 0

    # Count revisions: keys present in both, value differs.
    merged = existing.merge(new, on=key_cols, suffixes=("_old", "_new"), how="inner")
    n_revised = 0
    for vc in value_cols:
        old, newv = merged[f"{vc}_old"], merged[f"{vc}_new"]
        diff = (old.fillna(-1e18) - newv.fillna(-1e18)).abs() > 0.01
        n_revised += int(diff.sum())

    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=key_cols, keep="last")
    combined = combined.sort_values(key_cols).reset_index(drop=True)
    return combined, n_revised


def update_load(start, end) -> int:
    print(f"\n=== LOAD update ({start} -> {end}) ===")
    parts = [fetch_load(z, start, end) for z in BIDDING_ZONES]
    new = pd.concat([p for p in parts if len(p)], ignore_index=True)
    existing = pd.read_parquet(LOAD_PARQUET) if LOAD_PARQUET.exists() else pd.DataFrame()
    if not existing.empty:
        existing["timestamp_utc"] = pd.to_datetime(existing["timestamp_utc"], utc=True)
    combined, n_rev = _merge(existing, new, ["timestamp_utc", "zone"], ["load_mw"])
    combined.to_parquet(LOAD_PARQUET, index=False)
    print(f"  {len(existing):,} -> {len(combined):,} rows ({n_rev} revised)")
    return n_rev


def update_generation(start, end) -> int:
    print(f"\n=== GENERATION update ({start} -> {end}) ===")
    parts = [fetch_generation(z, start, end) for z in BIDDING_ZONES]
    new = pd.concat([p for p in parts if len(p)], ignore_index=True)
    existing = pd.read_parquet(GEN_PARQUET) if GEN_PARQUET.exists() else pd.DataFrame()
    if not existing.empty:
        existing["timestamp_utc"] = pd.to_datetime(existing["timestamp_utc"], utc=True)
    combined, n_rev = _merge(existing, new,
                             ["timestamp_utc", "zone", "psr_type"],
                             ["generation_mw", "consumption_mw"])
    combined.to_parquet(GEN_PARQUET, index=False)
    print(f"  {len(existing):,} -> {len(combined):,} rows ({n_rev} revised)")
    return n_rev


def update_flows(start, end) -> int:
    print(f"\n=== FLOWS update ({start} -> {end}) ===")
    parts = []
    for a, b in ALL_BORDERS:
        for fz, tz in [(a, b), (b, a)]:
            df = fetch_flow(fz, tz, start, end)
            if len(df):
                parts.append(df)
    new = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["timestamp_utc", "from_zone", "to_zone", "flow_mw"])
    existing = pd.read_parquet(FLOW_PARQUET) if FLOW_PARQUET.exists() else pd.DataFrame()
    if not existing.empty:
        existing["timestamp_utc"] = pd.to_datetime(existing["timestamp_utc"], utc=True)
    combined, n_rev = _merge(existing, new,
                             ["timestamp_utc", "from_zone", "to_zone"], ["flow_mw"])
    combined.to_parquet(FLOW_PARQUET, index=False)
    print(f"  {len(existing):,} -> {len(combined):,} rows ({n_rev} revised)")
    return n_rev


def compute_data_end_utc() -> str:
    """Latest UTC date for which we have a complete load day (>=23 hourly
    rows in IT_NORD). Matches the dashboard's completeness rule, so the Home
    badge agrees with the latest day visible on the charts.
    """
    if not LOAD_PARQUET.exists():
        return ""
    df = pd.read_parquet(LOAD_PARQUET, columns=["timestamp_utc", "zone"])
    df = df[df["zone"] == "IT_NORD"]
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    counts = df.groupby(df["timestamp_utc"].dt.date).size()
    complete = counts[counts >= 23]
    return str(complete.index.max()) if len(complete) else ""


def write_status(end, revisions: dict):
    status = {}
    if STATUS_JSON.exists():
        status = json.loads(STATUS_JSON.read_text())
    data_end = compute_data_end_utc() or str(pd.Timestamp(end).date())
    status.update({
        "last_run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_run_status": "success",
        "data_end": data_end,
        "revisions_last_run": revisions,
    })
    status.setdefault("data_start", "2016-01-01")
    STATUS_JSON.write_text(json.dumps(status, indent=2))
    print(f"\n  wrote {STATUS_JSON} (data_end={data_end})")


def main():
    ap = argparse.ArgumentParser(description="Incremental ENTSO-e update.")
    ap.add_argument("--lookback", type=int, default=14,
                    help="Days back from today to re-fetch (default 14)")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    end = pd.Timestamp.utcnow().normalize()
    start = (end - pd.Timedelta(days=args.lookback)).strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    t0 = datetime.now()
    rev = {
        "load": update_load(start, end_s),
        "generation": update_generation(start, end_s),
        "flows": update_flows(start, end_s),
    }
    write_status(end_s, rev)
    total_rev = sum(rev.values())
    print(f"\nDONE in {datetime.now() - t0}. Total revised rows: {total_rev}")
    if total_rev:
        print(f"::notice::Past data revised this run: {rev}")


if __name__ == "__main__":
    main()
