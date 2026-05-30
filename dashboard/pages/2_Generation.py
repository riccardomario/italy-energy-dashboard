"""Generation page — actual generation per production type, daily climatology."""

import streamlit as st

from lib import charts, data
from lib.auth import check_password

st.set_page_config(page_title="Generation — Italy Energy", page_icon="⚡", layout="wide")

if not check_password():
    st.stop()

st.title("Generation")

# --- Controls (sidebar) ---
with st.sidebar:
    st.header("Options")
    zone = st.selectbox("Geographic area", data.ZONE_OPTIONS, index=0)
    tech = st.selectbox("Technology", data.GEN_TECH_OPTIONS, index=0)
    mode = "Generation"
    if tech in data.STORAGE_TECHS:
        mode = st.radio("Storage view", data.STORAGE_MODES, index=0,
                        help="Net = Generation − Consumption")
    unit = st.radio("Unit", list(data.UNITS.keys()), index=0, horizontal=True)
    tz_label = st.radio("Timezone", list(data.TZ_OPTIONS.keys()), index=0)

tz = data.TZ_OPTIONS[tz_label]

# --- Data ---
daily = data.generation_daily(zone, tech, mode, tz)
if daily.empty:
    st.warning("No data available for this selection.")
    st.stop()

pivot = data.build_year_matrix(daily, unit)

# --- Chart ---
mode_suffix = f" — {mode}" if tech in data.STORAGE_TECHS else ""
title = f"{zone} — {tech}{mode_suffix} ({unit}, {tz_label})"
fig = charts.make_climatology_chart(pivot, unit_label=unit, title=title)
st.plotly_chart(fig, use_container_width=True)

# --- CSV download (same unit as displayed) ---
export = data.matrix_for_export(pivot)
csv = export.to_csv(index=False).encode("utf-8")
tech_slug = tech.replace(" ", "")
mode_slug = f"_{mode}" if tech in data.STORAGE_TECHS else ""
unit_slug = unit.replace("/", "-").replace(" ", "")
fname = f"generation_{zone}_{tech_slug}{mode_slug}_{unit_slug}.csv"
st.download_button(
    "Download data (CSV)", data=csv, file_name=fname, mime="text/csv",
)

st.caption(
    f"Values in **{unit}**, aggregated to daily in **{tz_label}**. "
    "Incomplete days (including today) are excluded."
)
