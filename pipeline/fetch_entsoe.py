"""
Thin wrapper around entsoe-py that returns tidy DataFrames in UTC hourly
resolution, ready to be appended to the parquet stores.

Three public functions:
  - fetch_load(zone, start, end)        -> [timestamp_utc, zone, load_mw]
  - fetch_generation(zone, start, end)  -> [timestamp_utc, zone, psr_type,
                                            generation_mw, consumption_mw]
  - fetch_flow(from_zone, to_zone, s, e) -> [timestamp_utc, from_zone,
                                             to_zone, flow_mw]

All functions:
  - take pandas Timestamps in any tz (re-localized to Europe/Brussels for the API)
  - chunk the request into 1-year windows automatically
  - resample to hourly mean (handles 15-min Italian data after 2025)
  - retry each chunk up to 3 times on transient API errors
"""

from __future__ import annotations

import time
import tomllib
from pathlib import Path

import pandas as pd
from entsoe import EntsoePandasClient

API_TZ = "Europe/Brussels"
CHUNK_DAYS = 365
MAX_RETRIES = 3
RETRY_SLEEP_SEC = 5

_ROOT = Path(__file__).resolve().parent.parent
_SECRETS_PATH = _ROOT / ".streamlit" / "secrets.toml"

_client: EntsoePandasClient | None = None


def get_client() -> EntsoePandasClient:
    """Lazy-load a singleton client reading the token from secrets.toml."""
    global _client
    if _client is not None:
        return _client
    if not _SECRETS_PATH.exists():
        raise FileNotFoundError(
            f"secrets.toml not found at {_SECRETS_PATH}. "
            "Run `py setup_local.py` and fill in the values."
        )
    with open(_SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)
    token = secrets.get("ENTSOE_API_TOKEN")
    if not token or token.startswith("your-"):
        raise ValueError("ENTSOE_API_TOKEN missing or placeholder in secrets.toml")
    _client = EntsoePandasClient(api_key=token)
    return _client


def _to_brussels(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tz is None:
        ts = ts.tz_localize(API_TZ)
    else:
        ts = ts.tz_convert(API_TZ)
    return ts


def _chunks(start: pd.Timestamp, end: pd.Timestamp, days: int = CHUNK_DAYS):
    cur = start
    step = pd.Timedelta(days=days)
    while cur < end:
        nxt = min(cur + step, end)
        yield cur, nxt
        cur = nxt


def _to_hourly_utc(df_or_series) -> pd.DataFrame | pd.Series:
    """Convert index to UTC, resample to hourly mean (drop incomplete tail hour)."""
    obj = df_or_series
    if obj is None or len(obj) == 0:
        return obj
    if obj.index.tz is None:
        obj.index = obj.index.tz_localize(API_TZ)
    obj.index = obj.index.tz_convert("UTC")
    # Resample to hourly mean. For load/generation/flows (all MW), mean over the
    # sub-hour samples is the correct hourly average power.
    obj = obj.resample("1h").mean()
    return obj


def _retry(fn, *args, **kwargs):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as ex:  # noqa: BLE001
            last_err = ex
            msg = str(ex)[:120]
            print(f"      retry {attempt}/{MAX_RETRIES} after error: {msg}")
            time.sleep(RETRY_SLEEP_SEC * attempt)
    raise RuntimeError(f"giving up after {MAX_RETRIES} retries: {last_err}")


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def fetch_load(zone: str, start, end) -> pd.DataFrame:
    client = get_client()
    s = _to_brussels(start)
    e = _to_brussels(end)
    parts = []
    for cs, ce in _chunks(s, e):
        print(f"    load  {zone}  {cs:%Y-%m-%d} -> {ce:%Y-%m-%d}")
        try:
            part = _retry(client.query_load, zone, start=cs, end=ce)
        except Exception as ex:  # noqa: BLE001
            print(f"      SKIP chunk: {ex}")
            continue
        if part is not None and len(part) > 0:
            parts.append(part)
    if not parts:
        return pd.DataFrame(columns=["timestamp_utc", "zone", "load_mw"])
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = _to_hourly_utc(df)
    # entsoe-py returns a DataFrame with column "Actual Load"
    if isinstance(df, pd.DataFrame):
        col = df.columns[0]
        s_load = df[col]
    else:
        s_load = df
    out = pd.DataFrame({
        "timestamp_utc": s_load.index,
        "zone": zone,
        "load_mw": s_load.values,
    })
    return out.dropna(subset=["load_mw"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# GENERATION
# ---------------------------------------------------------------------------

_GEN_COLS = ["timestamp_utc", "zone", "psr_type", "generation_mw", "consumption_mw"]


def _gen_chunk_to_long(df: pd.DataFrame, zone: str) -> pd.DataFrame:
    """Convert one chunk's wide DataFrame into long-format rows.
    Handles both flat columns and MultiIndex (PsrType, Gen/Cons sub-columns).
    """
    rows = []
    if isinstance(df.columns, pd.MultiIndex):
        psrs = df.columns.get_level_values(0).unique()
        for psr in psrs:
            sub = df[psr]
            if isinstance(sub, pd.Series):
                sub = sub.to_frame("Actual Aggregated")
            gen = sub["Actual Aggregated"] if "Actual Aggregated" in sub.columns else None
            cons = sub["Actual Consumption"] if "Actual Consumption" in sub.columns else None
            base = gen if gen is not None else cons
            if base is None:
                continue
            rows.append(pd.DataFrame({
                "timestamp_utc": base.index,
                "zone": zone,
                "psr_type": str(psr),
                "generation_mw": gen.values if gen is not None else pd.NA,
                "consumption_mw": cons.values if cons is not None else pd.NA,
            }))
    else:
        for psr in df.columns:
            col = df[psr]
            if isinstance(col, pd.DataFrame):
                col = col.iloc[:, 0]
            rows.append(pd.DataFrame({
                "timestamp_utc": col.index,
                "zone": zone,
                "psr_type": str(psr),
                "generation_mw": col.values,
                "consumption_mw": pd.NA,
            }))
    if not rows:
        return pd.DataFrame(columns=_GEN_COLS)
    out = pd.concat(rows, ignore_index=True)
    mask = out["generation_mw"].notna() | out["consumption_mw"].notna()
    return out[mask].reset_index(drop=True)


def fetch_generation(zone: str, start, end) -> pd.DataFrame:
    """
    Returns long-format with one row per (timestamp, psr_type).
    Includes both generation_mw and consumption_mw (consumption only populated
    for storage technologies like B10 Pumped Hydro).
    """
    client = get_client()
    s = _to_brussels(start)
    e = _to_brussels(end)
    long_parts = []
    for cs, ce in _chunks(s, e):
        print(f"    gen   {zone}  {cs:%Y-%m-%d} -> {ce:%Y-%m-%d}")
        try:
            wide = _retry(client.query_generation, zone, start=cs, end=ce, psr_type=None)
        except Exception as ex:  # noqa: BLE001
            print(f"      SKIP chunk: {ex}")
            continue
        if wide is None or len(wide) == 0:
            continue
        wide = wide[~wide.index.duplicated(keep="first")].sort_index()
        wide = _to_hourly_utc(wide)
        long_parts.append(_gen_chunk_to_long(wide, zone))
    if not long_parts:
        return pd.DataFrame(columns=_GEN_COLS)
    out = pd.concat(long_parts, ignore_index=True)
    out = out.drop_duplicates(subset=["timestamp_utc", "zone", "psr_type"], keep="first")
    return out.sort_values(["timestamp_utc", "psr_type"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# CROSS-BORDER FLOWS
# ---------------------------------------------------------------------------

def fetch_flow(from_zone: str, to_zone: str, start, end) -> pd.DataFrame:
    """One direction only. Call twice (swap) to get the reverse flow."""
    client = get_client()
    s = _to_brussels(start)
    e = _to_brussels(end)
    parts = []
    for cs, ce in _chunks(s, e):
        print(f"    flow  {from_zone} -> {to_zone}  {cs:%Y-%m-%d} -> {ce:%Y-%m-%d}")
        try:
            part = _retry(client.query_crossborder_flows,
                          from_zone, to_zone, start=cs, end=ce)
        except Exception as ex:  # noqa: BLE001
            print(f"      SKIP chunk: {ex}")
            continue
        if part is not None and len(part) > 0:
            parts.append(part)
    if not parts:
        return pd.DataFrame(columns=["timestamp_utc", "from_zone", "to_zone", "flow_mw"])
    s_flow = pd.concat(parts)
    s_flow = s_flow[~s_flow.index.duplicated(keep="first")].sort_index()
    s_flow = _to_hourly_utc(s_flow)
    out = pd.DataFrame({
        "timestamp_utc": s_flow.index,
        "from_zone": from_zone,
        "to_zone": to_zone,
        "flow_mw": s_flow.values,
    })
    return out.dropna(subset=["flow_mw"]).reset_index(drop=True)
