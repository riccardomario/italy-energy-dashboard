"""Transmission page — cross-border physical flows (net), daily climatology."""

import streamlit as st

from lib import charts, data
from lib.auth import check_password

st.set_page_config(page_title="Transmission — Italy Energy", page_icon="⚡", layout="wide")

if not check_password():
    st.stop()

st.title("Transmission")
st.caption(
    "Net **physical** cross-border flows. Positive (+) = the direction shown in "
    "the selector (imports to Italy for external borders). Net = gross flow one "
    "way minus the other."
)

# --- Controls (sidebar) ---
with st.sidebar:
    st.header("Options")
    border = st.selectbox("Border / corridor", data.BORDER_OPTIONS_LIST, index=0)
    unit = st.radio("Unit", list(data.UNITS.keys()), index=0, horizontal=True)
    tz_label = st.radio("Timezone", list(data.TZ_OPTIONS.keys()), index=0)

tz = data.TZ_OPTIONS[tz_label]

# --- Data ---
daily = data.flow_daily(border, tz)
if daily.empty:
    st.warning("No data available for this selection.")
    st.stop()

pivot = data.build_year_matrix(daily, unit)

# --- Chart ---
title = f"{border} ({unit}, {tz_label})"
fig = charts.make_climatology_chart(pivot, unit_label=unit, title=title)
st.plotly_chart(fig, use_container_width=True)

# --- CSV download (same unit as displayed) ---
export = data.matrix_for_export(pivot)
csv = export.to_csv(index=False).encode("utf-8")
border_slug = (border.split(" ")[0] + "_" + border.split(":")[-1].strip()) \
    .replace(" ", "").replace("→", "-").replace("(+)", "").replace("/", "-")
unit_slug = unit.replace("/", "-").replace(" ", "")
fname = f"flow_{border_slug}_{unit_slug}.csv"
st.download_button(
    "Download data (CSV)", data=csv, file_name=fname, mime="text/csv",
)

st.caption(
    f"Net flow in **{unit}**, aggregated to daily in **{tz_label}**. "
    "Incomplete days (including today) are excluded. North border total uses "
    "FR+CH+AT+SI (Austria data starts 2018)."
)
