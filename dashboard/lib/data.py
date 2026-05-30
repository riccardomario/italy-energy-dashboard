"""Data access layer: read parquet, aggregate hourly -> daily, build the
year-by-year matrix used for the climatology chart and CSV export.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"

# Geographic selector options. "Italy" = sum of all 7 bidding zones.
BIDDING_ZONES = [
    "IT_NORD", "IT_CNOR", "IT_CSUD",
    "IT_SUD", "IT_SICI", "IT_SARD", "IT_CALA",
]
ZONE_OPTIONS = ["Italy"] + BIDDING_ZONES

# Display unit -> conversion factor applied to MWh/day.
#   GWh/day      = MWh_day / 1000
#   Average GW   = MWh_day / 1000 / 24
UNITS = {
    "GWh/day": 1.0 / 1000.0,
    "Average GW": 1.0 / 1000.0 / 24.0,
}

TZ_OPTIONS = {
    "UTC": "UTC",
    "CET/CEST (Italy)": "Europe/Rome",
}

# Minimum hourly samples for a local day to count as complete. A normal day has
# 24h; the spring DST day has 23h, the autumn DST day 25h. Requiring >= 23 keeps
# all real days and drops the partial current day.
_MIN_HOURS = 23


@st.cache_data(show_spinner=False)
def load_status() -> dict:
    path = DATA_DIR / "last_update.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


@st.cache_data(show_spinner="Loading load data...")
def read_load() -> pd.DataFrame:
    """Hourly load: columns [timestamp_utc, zone, load_mw]."""
    df = pd.read_parquet(DATA_DIR / "load.parquet")
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df


# Display technology -> ENTSO-e PsrType name(s) as returned by entsoe-py.
# Ordered renewables -> thermal -> other. "Fossil Coal" merges hard coal +
# coal-derived gas (per spec). Waste and Other renewable surfaced separately.
TECH_MAP = {
    "Solar": ["Solar"],
    "Onshore Wind": ["Wind Onshore"],
    "Offshore Wind": ["Wind Offshore"],
    "Hydro Run-of-River": ["Hydro Run-of-river and poundage"],
    "Hydro Reservoir": ["Hydro Water Reservoir"],
    "Hydro Pumped Storage": ["Hydro Pumped Storage"],
    "Geothermal": ["Geothermal"],
    "Biomass": ["Biomass"],
    "Fossil Gas": ["Fossil Gas"],
    "Fossil Coal": ["Fossil Hard coal", "Fossil Coal-derived gas"],
    "Fossil Oil": ["Fossil Oil"],
    "Energy Storage": ["Energy storage"],
    "Other non-RES": ["Other"],
}
GEN_TECH_OPTIONS = list(TECH_MAP.keys())

# Storage technologies support a Generation / Consumption / Net view.
STORAGE_TECHS = {"Hydro Pumped Storage", "Energy Storage"}
STORAGE_MODES = ["Net", "Generation", "Consumption"]


@st.cache_data(show_spinner="Loading generation data...")
def read_generation() -> pd.DataFrame:
    """Hourly generation (long):
    columns [timestamp_utc, zone, psr_type, generation_mw, consumption_mw]."""
    df = pd.read_parquet(DATA_DIR / "generation.parquet")
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df


def _aggregate_daily(hourly: pd.Series, tz: str) -> pd.Series:
    """hourly: Series of MW indexed by UTC timestamp.
    Returns daily energy (MWh/day) indexed by local calendar date, dropping
    incomplete days. Each hourly MW value = MWh for that hour, so daily sum = MWh.
    """
    s = hourly.copy()
    s.index = s.index.tz_convert(tz)
    local_date = s.index.normalize().tz_localize(None)
    grouped = s.groupby(local_date)
    daily = grouped.sum()
    counts = grouped.size()
    daily = daily[counts >= _MIN_HOURS]
    daily.index = pd.to_datetime(daily.index)
    return daily


def load_daily(zone: str, tz: str) -> pd.Series:
    """Daily load energy (MWh/day) for a zone selection, indexed by local date."""
    df = read_load()
    if zone == "Italy":
        sub = df.groupby("timestamp_utc")["load_mw"].sum()
    else:
        sub = df[df["zone"] == zone].set_index("timestamp_utc")["load_mw"]
    sub = sub.sort_index()
    return _aggregate_daily(sub, tz)


def generation_daily(zone: str, tech: str, mode: str, tz: str) -> pd.Series:
    """Daily generation energy (MWh/day) for a technology + zone selection.

    mode applies only to storage techs:
      - "Generation"  -> generation_mw
      - "Consumption" -> consumption_mw
      - "Net"         -> generation_mw - consumption_mw
    For non-storage techs, generation_mw is always used.
    """
    df = read_generation()
    psrs = TECH_MAP[tech]
    sub = df[df["psr_type"].isin(psrs)]
    if zone != "Italy":
        sub = sub[sub["zone"] == zone]
    if sub.empty:
        return pd.Series(dtype="float64")

    if tech in STORAGE_TECHS and mode == "Consumption":
        val = sub["consumption_mw"]
    elif tech in STORAGE_TECHS and mode == "Net":
        val = sub["generation_mw"].fillna(0) - sub["consumption_mw"].fillna(0)
    else:
        val = sub["generation_mw"]

    hourly = val.groupby(sub["timestamp_utc"]).sum().sort_index()
    return _aggregate_daily(hourly, tz)


@st.cache_data(show_spinner="Loading flow data...")
def read_flows() -> pd.DataFrame:
    """Hourly cross-border flows (one direction per row):
    columns [timestamp_utc, from_zone, to_zone, flow_mw]."""
    df = pd.read_parquet(DATA_DIR / "flows.parquet")
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df


# Each border option maps to a list of (pos_from, pos_to) pairs. Net flow =
# sum of [flow(pos_from->pos_to) - flow(pos_to->pos_from)]. For external borders
# the positive direction is foreign -> Italy, i.e. positive = IMPORT to Italy.
# ME (Montenegro) and MT (Malta) are omitted: ENTSO-e returns no data for them
# under the queried zone codes.
BORDER_OPTIONS = {
    "France — net import (+)": [("FR", "IT_NORD")],
    "Switzerland — net import (+)": [("CH", "IT_NORD")],
    "Austria — net import (+)": [("AT", "IT_NORD")],
    "Slovenia — net import (+)": [("SI", "IT_NORD")],
    "Greece — net import (+)": [("GR", "IT_BRNN")],
    "North border total — net import (+) [FR+CH+AT+SI]": [
        ("FR", "IT_NORD"), ("CH", "IT_NORD"),
        ("AT", "IT_NORD"), ("SI", "IT_NORD"),
    ],
    "Internal: Nord → Centre-North (+)": [("IT_NORD", "IT_CNOR")],
    "Internal: Centre-North → Centre-South (+)": [("IT_CNOR", "IT_CSUD")],
    "Internal: Centre-South → South (+)": [("IT_CSUD", "IT_SUD")],
    "Internal: Centre-South → Sardinia (+)": [("IT_CSUD", "IT_SARD")],
    "Internal: South → Calabria (+)": [("IT_SUD", "IT_CALA")],
    "Internal: Calabria → Sicily (+)": [("IT_CALA", "IT_SICI")],
}
BORDER_OPTIONS_LIST = list(BORDER_OPTIONS.keys())


def _net_hourly(df: pd.DataFrame, pos_from: str, pos_to: str) -> pd.Series:
    fwd = df[(df["from_zone"] == pos_from) & (df["to_zone"] == pos_to)] \
        .groupby("timestamp_utc")["flow_mw"].sum()
    rev = df[(df["from_zone"] == pos_to) & (df["to_zone"] == pos_from)] \
        .groupby("timestamp_utc")["flow_mw"].sum()
    idx = fwd.index.union(rev.index)
    return fwd.reindex(idx).fillna(0) - rev.reindex(idx).fillna(0)


def flow_daily(border: str, tz: str) -> pd.Series:
    """Daily net flow energy (MWh/day, signed) for a border selection."""
    df = read_flows()
    pairs = BORDER_OPTIONS[border]
    nets = [_net_hourly(df, a, b) for a, b in pairs]
    if not nets:
        return pd.Series(dtype="float64")
    combined = pd.concat(nets, axis=1).fillna(0).sum(axis=1).sort_index()
    return _aggregate_daily(combined, tz)


def generation_daily_psrs(zone: str, psr_list: list[str], tz: str) -> pd.Series:
    """Daily generation energy (MWh/day) summed over several PsrType names.
    Used for composite views like Wind = Onshore + Offshore.
    """
    df = read_generation()
    sub = df[df["psr_type"].isin(psr_list)]
    if zone != "Italy":
        sub = sub[sub["zone"] == zone]
    if sub.empty:
        return pd.Series(dtype="float64")
    hourly = sub["generation_mw"].groupby(sub["timestamp_utc"]).sum().sort_index()
    return _aggregate_daily(hourly, tz)


def build_year_matrix(daily: pd.Series, unit: str) -> pd.DataFrame:
    """Pivot a daily series into rows = day-of-year (MM-DD), columns = year.
    Values converted to the chosen display unit.
    """
    factor = UNITS[unit]
    df = daily.to_frame("value")
    df["year"] = df.index.year
    df["md"] = df.index.strftime("%m-%d")
    pivot = df.pivot_table(index="md", columns="year", values="value", aggfunc="first")
    pivot = pivot.sort_index() * factor
    return pivot


def matrix_for_export(pivot: pd.DataFrame) -> pd.DataFrame:
    """Format the year matrix for CSV download: a readable Date column plus one
    column per year. Uses a leap reference year so 02-29 has a slot.
    """
    out = pivot.copy()
    dates = pd.to_datetime("2000-" + out.index, format="%Y-%m-%d")
    out.insert(0, "Date", dates.strftime("%d %b"))
    out.index.name = "MM-DD"
    return out.reset_index(drop=True)
