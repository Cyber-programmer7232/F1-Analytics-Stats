"""Mode 6: Qualifying head-to-head (FastF1). Two drivers' fastest laps
overlaid: speed, gap, throttle, brake and gear, plus a track map showing
who was quicker in each part of the lap."""
from datetime import datetime, timezone

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from f1app import fastf1_data as fd
from f1app.modes.lap_times import fmt_lap

MINISECTORS = 25


def compare(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Put B on A's distance grid. Gap > 0 means B is behind A at that point."""
    out = a[["Distance", "Time", "Speed", "X", "Y"]].copy()
    out["TimeB"] = np.interp(out["Distance"], b["Distance"], b["Time"])
    out["SpeedB"] = np.interp(out["Distance"], b["Distance"], b["Speed"])
    out["Gap"] = out["TimeB"] - out["Time"]
    return out


def minisector_winners(cmp: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    edges = np.linspace(0, cmp["Distance"].max(), MINISECTORS + 1)
    cmp = cmp.copy()
    cmp["Minisector"] = np.clip(np.digitize(cmp["Distance"], edges) - 1, 0, MINISECTORS - 1) + 1
    avg = cmp.groupby("Minisector")[["Speed", "SpeedB"]].mean()
    winner = np.where(avg["Speed"] >= avg["SpeedB"], a, b)
    cmp["Faster"] = cmp["Minisector"].map(dict(zip(avg.index, winner)))
    return cmp


def render():
    st.header("🆚 Qualifying head-to-head")
    now_year = datetime.now(timezone.utc).year

    c1, c2, c3 = st.columns([1, 3, 2])
    year = c1.selectbox("Season", list(range(now_year, fd.FIRST_FASTF1_SEASON - 1, -1)), key="q_year")
    try:
        events = fd.past_events(year)
    except Exception as exc:
        st.error(f"Could not load the {year} schedule: {exc}")
        return
    if events.empty:
        st.info(f"No {year} races have happened yet.")
        return
    labels = {f"R{r.RoundNumber} · {r.EventName}": r for r in events.itertuples()}
    event = labels[c2.selectbox("Race weekend", list(labels), key="q_event")]
    sessions = fd.quali_sessions(event.EventFormat)
    session = sessions[c3.radio("Session", list(sessions), horizontal=True, key="q_session")]
    rnd = int(event.RoundNumber)

    try:
        with st.spinner("Loading qualifying telemetry from FastF1. The first load of a session takes up to a couple of minutes."):
            results = fd.quali_results(year, rnd, session)
    except Exception as exc:
        st.error(f"Could not load this session: {exc}")
        return
    results = results.dropna(subset=["Best"])
    if len(results) < 2:
        st.info("Not enough drivers set a lap time in this session.")
        return

    names = {r.Abbreviation: f"{r.Abbreviation} · {r.FullName} ({r.TeamName})" for r in results.itertuples()}
    codes = list(names)
    d1, d2 = st.columns(2)
    a = d1.selectbox("Driver A", codes, index=0, format_func=names.get, key="q_a")
    b = d2.selectbox("Driver B", codes, index=1, format_func=names.get, key="q_b")
    if a == b:
        st.info("Pick two different drivers.")
        return

    try:
        info_a, tel_a = fd.fastest_lap_telemetry(year, rnd, session, a)
        info_b, tel_b = fd.fastest_lap_telemetry(year, rnd, session, b)
    except Exception as exc:
        st.error(f"Could not load lap telemetry: {exc}")
        return

    colors = results.set_index("Abbreviation")["Color"]
    col_a, col_b = colors.get(a, "#1f77b4"), colors.get(b, "#ff7f0e")
    if col_a.lower() == col_b.lower():  # teammates share a colour
        col_b = "#9e9e9e"
    color = alt.Color("Driver:N", scale=alt.Scale(domain=[a, b], range=[col_a, col_b]), title=None)

    gap = info_b["LapSeconds"] - info_a["LapSeconds"]
    m1, m2, m3 = st.columns(3)
    m1.metric(f"{a} fastest lap", fmt_lap(info_a["LapSeconds"]), info_a.get("Compound") or None, delta_color="off")
    m2.metric(f"{b} fastest lap", fmt_lap(info_b["LapSeconds"]), info_b.get("Compound") or None, delta_color="off")
    quicker = a if gap > 0 else b
    m3.metric("Gap", f"{abs(gap):.3f} s", f"{quicker} quicker", delta_color="off")

    both = pd.concat([tel_a.assign(Driver=a), tel_b.assign(Driver=b)], ignore_index=True)
    dmax = float(max(tel_a["Distance"].max(), tel_b["Distance"].max()))
    x = alt.X("Distance:Q", title="Distance into lap (m)", scale=alt.Scale(domain=[0, dmax]))
    def trace(field, title, height, step=False):
        mark = alt.Chart(both).mark_line(interpolate="step-after" if step else "linear", strokeWidth=1.6)
        return mark.encode(x=x, y=alt.Y(f"{field}:Q", title=title), color=color,
                           tooltip=["Driver", alt.Tooltip("Distance:Q", format=".0f"), field]).properties(height=height)

    speed = trace("Speed", "Speed (km/h)", 260)
    corner_df = fd.corners(year, rnd, session)
    if not corner_df.empty:
        rules = alt.Chart(corner_df).mark_rule(strokeDash=[2, 3], opacity=0.35).encode(x="Distance:Q")
        labels_ = alt.Chart(corner_df).mark_text(dy=-6, fontSize=10, opacity=0.7).encode(
            x="Distance:Q", y=alt.value(0), text="Corner:N")
        speed = speed + rules + labels_

    cmp = minisector_winners(compare(tel_a, tel_b), a, b)
    gap_chart = (
        alt.Chart(cmp)
        .mark_area(line=True, opacity=0.25)
        .encode(x=x, y=alt.Y("Gap:Q", title=f"{b} behind {a} (s)"),
                tooltip=[alt.Tooltip("Distance:Q", format=".0f"), alt.Tooltip("Gap:Q", format="+.3f")])
        .properties(height=140)
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(opacity=0.5).encode(y="y:Q")
    st.altair_chart(speed, width="stretch")
    st.altair_chart(gap_chart + zero, width="stretch")
    st.altair_chart(trace("Throttle", "Throttle (%)", 120), width="stretch")
    st.altair_chart(trace("Brake", "Brake", 80, step=True), width="stretch")
    st.altair_chart(trace("Gear", "Gear", 120, step=True), width="stretch")
    st.caption(f"In the gap chart, rising means {b} is losing time to {a} on that part of the track, and falling means {b} is gaining.")

    st.subheader("Who was faster where")
    share = cmp.drop_duplicates("Minisector")["Faster"].value_counts()
    st.caption(
        f"The lap is split into {MINISECTORS} equal parts, each coloured by the driver with the higher average speed there. "
        f"{a} won {share.get(a, 0)}, {b} won {share.get(b, 0)}."
    )
    map_df = cmp.iloc[::2].rename(columns={"Faster": "Driver"})
    xr = (map_df["X"].min(), map_df["X"].max())
    yr = (map_df["Y"].min(), map_df["Y"].max())
    span = max(xr[1] - xr[0], yr[1] - yr[0]) / 2 or 1
    cx, cy = sum(xr) / 2, sum(yr) / 2
    track = (
        alt.Chart(map_df)
        .mark_circle(size=22, opacity=0.9)
        .encode(
            x=alt.X("X:Q", axis=None, scale=alt.Scale(domain=[cx - span, cx + span])),
            y=alt.Y("Y:Q", axis=None, scale=alt.Scale(domain=[cy - span, cy + span])),
            color=color,
            tooltip=["Driver", "Minisector"],
        )
        .properties(width=480, height=480)
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(track)
