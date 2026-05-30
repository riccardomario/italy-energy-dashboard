"""Plotly climatology chart: historical min-max band + previous year + current
year, matching the provided chart_sample styling.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

BAND_COLOR = "rgba(200,200,200,0.30)"   # lighter fill
BORDER_COLOR = "#9E9E9E"                # thin solid band edges
PREV_COLOR = "#3E7CB1"   # blue dashed (previous year)
CURR_COLOR = "#B5123E"   # crimson solid (current year)


def _to_axis_dates(md_index: pd.Index) -> pd.DatetimeIndex:
    # Map MM-DD strings onto a leap reference year (2000) so 02-29 has a slot.
    return pd.to_datetime("2000-" + md_index, format="%Y-%m-%d")


def make_climatology_chart(pivot: pd.DataFrame, unit_label: str,
                           title: str = "", current_year: int | None = None,
                           height: int = 480) -> go.Figure:
    """pivot: rows = MM-DD, columns = year, values in display unit.

    current_year anchors the colour roles to the real calendar year (not the last
    year of data), so a series that stopped years ago shows as a historical band
    only — rather than mislabelling its final year as "current".
    """
    years = sorted(int(c) for c in pivot.columns)
    if current_year is None:
        current_year = pd.Timestamp.now().year
    curr_year = current_year
    prev_year = curr_year - 1
    band_years = [y for y in years if y <= curr_year - 2]

    x = _to_axis_dates(pivot.index)
    fig = go.Figure()
    hov = "%{y:.1f}<extra></extra>"

    # A single historical year can't form a band; draw it as a labelled line.
    if len(band_years) == 1:
        y1 = band_years[0]
        fig.add_trace(go.Scatter(
            x=x, y=pivot[y1], mode="lines",
            line=dict(color="#6E6E6E", width=1.8),
            name=str(y1), showlegend=True, hovertemplate=hov,
        ))
        band_years = []

    # Historical min-max band (drawn first so it sits behind the lines)
    if band_years:
        band = pivot[band_years]
        ymin = band.min(axis=1)
        ymax = band.max(axis=1)
        ymed = band.median(axis=1)
        band_label = f"{band_years[0]}-{band_years[-1]}"
        # Band: thin solid edges + light fill; no hover (stats carried separately).
        fig.add_trace(go.Scatter(
            x=x, y=ymax, mode="lines", line=dict(width=0.8, color=BORDER_COLOR),
            hoverinfo="skip", showlegend=False, name="band_max",
        ))
        fig.add_trace(go.Scatter(
            x=x, y=ymin, mode="lines", line=dict(width=0.8, color=BORDER_COLOR),
            fill="tonexty", fillcolor=BAND_COLOR, hoverinfo="skip",
            name=f"Range {band_label}",
        ))
        # Invisible stats trace: carries Max/Median/Min in one tidy hover block.
        customdata = np.column_stack([ymax.values, ymed.values, ymin.values])
        fig.add_trace(go.Scatter(
            x=x, y=ymed, mode="lines", line=dict(width=0),
            showlegend=False, name=band_label, customdata=customdata,
            hovertemplate=(
                "Max: %{customdata[0]:.1f}<br>"
                "Median: %{customdata[1]:.1f}<br>"
                "Min: %{customdata[2]:.1f}<extra></extra>"
            ),
        ))

    # Previous year (dashed blue)
    if prev_year in pivot.columns:
        fig.add_trace(go.Scatter(
            x=x, y=pivot[prev_year], mode="lines",
            line=dict(color=PREV_COLOR, width=1.6, dash="dash"),
            name=str(prev_year), hovertemplate=hov,
        ))

    # Current year (solid crimson)
    if curr_year in pivot.columns:
        fig.add_trace(go.Scatter(
            x=x, y=pivot[curr_year], mode="lines",
            line=dict(color=CURR_COLOR, width=2.2),
            name=str(curr_year), hovertemplate=hov,
        ))

    # Net-flow series can be negative (exports); use a signed axis + zero line.
    has_negative = bool((pivot.min(numeric_only=True) < 0).any())
    if has_negative:
        fig.add_hline(y=0, line_width=1, line_color="#888888")

    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=40, r=20, t=50 if title else 20, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="center", x=0.5),
        hovermode="x unified",
        plot_bgcolor="white",
        yaxis=dict(title=unit_label, gridcolor="#EEEEEE",
                   rangemode="normal" if has_negative else "tozero"),
        xaxis=dict(
            gridcolor="#F5F5F5",
            range=[x.min(), x.max()],
            # Dynamic tick density + label format that adapts to zoom level.
            tickformatstops=[
                dict(dtickrange=[None, 604800000], value="%d %b"),       # <= ~1 week: daily
                dict(dtickrange=[604800000, "M1"], value="%d %b"),       # weeks
                dict(dtickrange=["M1", "M12"], value="%b"),              # months
                dict(dtickrange=["M12", None], value="%Y"),
            ],
            showspikes=True, spikemode="across", spikesnap="cursor",
            spikethickness=1, spikedash="dot", spikecolor="#9E9E9E",
        ),
    )
    return fig
