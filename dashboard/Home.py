"""Italy Energy Dashboard — landing page."""

from datetime import datetime

import streamlit as st

from lib import charts, data
from lib.auth import check_password

st.set_page_config(page_title="Italy Energy Dashboard", page_icon="⚡", layout="wide")

if not check_password():
    st.stop()

st.title("Italy Energy Dashboard")
st.markdown(
    "Daily Italian power-system data from the "
    "[ENTSO-e Transparency Platform](https://transparency.entsoe.eu/). "
    "Use the pages in the sidebar to explore **Load**, **Generation**, and "
    "**Transmission**."
)

status = data.load_status()
if status:
    raw = status.get("last_run_utc", "")
    try:
        ts = datetime.fromisoformat(raw)
        upd_date = ts.strftime("%Y-%m-%d")
        upd_time = ts.strftime("%H:%M")
    except ValueError:
        upd_date, upd_time = raw or "n/a", ""

    st.markdown("##### Last successful update (UTC)")
    st.markdown(f"**Date:** {upd_date}")
    st.markdown(f"**Time:** {upd_time}")
    st.markdown("##### Data coverage")
    st.markdown(
        f"**{status.get('data_start', '?')} → {status.get('data_end', '?')}**"
    )
else:
    st.info("No update status file found yet.")

st.markdown("---")
st.caption(
    "Each chart shows the current year (solid), previous year (dashed), and the "
    "min–max range of prior years (grey band). Switch units (GWh/day ↔ average "
    "GW) and timezone per page, and download the underlying data per chart."
)

# --- Overview grid: Italy, Average GW, UTC ---
st.subheader("Italy overview — Average GW (UTC)")

UNIT = "Average GW"
TZ = "UTC"


@st.cache_data(show_spinner=False)
def _overview_series():
    return {
        "Power Load": data.load_daily("Italy", TZ),
        "Solar": data.generation_daily("Italy", "Solar", "Generation", TZ),
        "Wind (Onshore + Offshore)": data.generation_daily_psrs(
            "Italy", ["Wind Onshore", "Wind Offshore"], TZ),
        "Hydro (Run-of-River + Reservoir)": data.generation_daily_psrs(
            "Italy", ["Hydro Run-of-river and poundage", "Hydro Water Reservoir"], TZ),
        "Fossil Gas": data.generation_daily("Italy", "Fossil Gas", "Generation", TZ),
        "North Border Total (net import +)": data.flow_daily(
            "North border total — net import (+) [FR+CH+AT+SI]", TZ),
    }


series = _overview_series()
items = list(series.items())
for row_start in range(0, len(items), 2):
    cols = st.columns(2)
    for col, (name, daily) in zip(cols, items[row_start:row_start + 2]):
        with col:
            if daily.empty:
                st.warning(f"No data for {name}.")
                continue
            pivot = data.build_year_matrix(daily, UNIT)
            fig = charts.make_climatology_chart(
                pivot, unit_label=UNIT, title=name, height=320)
            st.plotly_chart(fig, use_container_width=True)
