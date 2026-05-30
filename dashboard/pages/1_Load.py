"""Load page — power load, daily climatology view."""

import streamlit as st

from lib import charts, data
from lib.auth import check_password

st.set_page_config(page_title="Power Load — Italy Energy", page_icon="⚡", layout="wide")

if not check_password():
    st.stop()

st.title("Power Load")

# --- Controls (sidebar) ---
with st.sidebar:
    st.header("Options")
    zone = st.selectbox("Geographic area", data.ZONE_OPTIONS, index=0)
    unit = st.radio("Unit", list(data.UNITS.keys()), index=0, horizontal=True)
    tz_label = st.radio("Timezone", list(data.TZ_OPTIONS.keys()), index=0)

tz = data.TZ_OPTIONS[tz_label]

# --- Data ---
daily = data.load_daily(zone, tz)
if daily.empty:
    st.warning("No data available for this selection.")
    st.stop()

pivot = data.build_year_matrix(daily, unit)

# --- Chart ---
title = f"{zone} — Power Load ({unit}, {tz_label})"
fig = charts.make_climatology_chart(pivot, unit_label=unit, title=title)
st.plotly_chart(fig, use_container_width=True)

# --- CSV download (same unit as displayed) ---
export = data.matrix_for_export(pivot)
csv = export.to_csv(index=False).encode("utf-8")
fname = f"load_{zone}_{unit.replace('/', '-').replace(' ', '')}.csv"
st.download_button(
    "Download data (CSV)", data=csv, file_name=fname, mime="text/csv",
)

st.caption(
    f"Values in **{unit}**, aggregated to daily in **{tz_label}**. "
    "Incomplete days (including today) are excluded."
)
