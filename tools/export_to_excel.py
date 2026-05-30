"""
On-demand local backup: read the parquet stores and write a single Excel
workbook with one sheet per series, matching the csv_sample.xlsx layout
(rows = day-of-year Jan 1 -> Dec 31, columns = years).

Run with:
    py tools/export_to_excel.py
    py tools/export_to_excel.py --unit "Average GW" --tz Europe/Rome

Output: italy_energy_export_<timestamp>.xlsx in the project folder.
Not part of the dashboard; purely a local archival utility.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))

from lib import data as dlib  # noqa: E402


def _matrix(daily: pd.Series, unit: str) -> pd.DataFrame:
    pivot = dlib.build_year_matrix(daily, unit)
    dates = pd.to_datetime("2000-" + pivot.index, format="%Y-%m-%d")
    out = pivot.copy()
    out.insert(0, "Date", dates.strftime("%d %b"))
    return out.reset_index(drop=True)


def build_sheets(unit: str, tz: str) -> dict[str, pd.DataFrame]:
    sheets: dict[str, pd.DataFrame] = {}

    # Load (Italy + each zone)
    for zone in dlib.ZONE_OPTIONS:
        s = dlib.load_daily(zone, tz)
        if not s.empty:
            sheets[f"Load_{zone}"] = _matrix(s, unit)

    # Generation (Italy, every technology; storage uses Net)
    for tech in dlib.GEN_TECH_OPTIONS:
        mode = "Net" if tech in dlib.STORAGE_TECHS else "Generation"
        s = dlib.generation_daily("Italy", tech, mode, tz)
        if not s.empty:
            name = f"Gen_{tech}".replace(" ", "")[:31]
            sheets[name] = _matrix(s, unit)

    # Flows (every border / corridor)
    for border in dlib.BORDER_OPTIONS_LIST:
        s = dlib.flow_daily(border, tz)
        if not s.empty:
            short = border.split("—")[0].split(":")[-1].strip().replace(" ", "")
            name = f"Flow_{short}"[:31]
            sheets[name] = _matrix(s, unit)

    return sheets


def main():
    ap = argparse.ArgumentParser(description="Export parquet stores to Excel.")
    ap.add_argument("--unit", default="GWh/day", choices=list(dlib.UNITS.keys()))
    ap.add_argument("--tz", default="UTC", help="UTC or Europe/Rome")
    args = ap.parse_args()

    print(f"Building Excel export (unit={args.unit}, tz={args.tz}) ...")
    sheets = build_sheets(args.unit, args.tz)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = ROOT / f"italy_energy_export_{stamp}.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    print(f"Wrote {len(sheets)} sheets -> {out_path}")


if __name__ == "__main__":
    main()
