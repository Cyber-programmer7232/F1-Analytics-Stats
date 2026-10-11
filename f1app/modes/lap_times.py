"""Mode 5: Race lap times (FastF1). Every driver's lap times through a race,
positions lap by lap, and a pace comparison on clean laps."""
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from f1app import fastf1_data as fd

SESSIONS = {"Race": "R", "Sprint": "S"}


def fmt_lap(seconds: float) -> str:
    if pd.isna(seconds):
        return ""
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


def clean_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Drop lap 1, pit in/out laps, Safety Car/VSC/red flag laps and anything
    slower than 107% of the typical clean lap."""
    c = laps[
        (laps["LapNumber"] > 1)
        & ~laps["PitIn"]
        & ~laps["PitOut"]
        & ~laps["Neutralised"]
        & laps["LapSeconds"].notna()
    ]
    if c.empty:
        return c
    return c[c["LapSeconds"] <= c["LapSeconds"].median() * 1.07]


def driver_scales(results: pd.DataFrame, drivers: list[str]):
    """Team colours per driver; the second driver of a team gets a dashed line."""
    info = results.set_index("Abbreviation")
    colors = [info.loc[d, "Color"] if d in info.index else "#888888" for d in drivers]
    seen, dash = {}, {}
    for d in drivers:
        team = info.loc[d, "TeamName"] if d in info.index else d
        dash[d] = "Second driver" if team in seen else "First driver"
        seen[team] = True
    return alt.Scale(domain=drivers, range=colors), dash


def summary_table(laps: pd.DataFrame, clean: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    g = laps.groupby("Driver")
    table = pd.DataFrame(
        {
            "Fastest lap": g["LapSeconds"].min().map(fmt_lap),
            "Median clean lap": clean.groupby("Driver")["LapSeconds"].median().map(fmt_lap),
            "Pit stops": g["PitIn"].sum().astype(int),
            "Laps": g["LapNumber"].max(),
        }
    )
    r = results.set_index("Abbreviation")[["FullName", "TeamName", "GridPosition", "Position", "Status"]]
    table = r.join(table, how="left").reset_index().rename(
        columns={"Abbreviation": "Code", "FullName": "Driver", "TeamName": "Team", "GridPosition": "Grid", "Position": "Finish"}
    )
    return table


def render():
    st.header("⏱️ Race lap times")
    now_year = datetime.now(timezone.utc).year

    c1, c2, c3 = st.columns([1, 3, 1])
    year = c1.selectbox("Season", list(range(now_year, fd.FIRST_FASTF1_SEASON - 1, -1)), key="lt_year")
    try:
        events = fd.past_events(year)
    except Exception as exc:  # FastF1 raises several error types for network problems
        st.error(f"Could not load the {year} schedule: {exc}")
        return
    if events.empty:
        st.info(f"No {year} races have happened yet.")
        return

    labels = {f"R{r.RoundNumber} · {r.EventName}": r for r in events.itertuples()}
    event = labels[c2.selectbox("Race", list(labels), key="lt_event")]
    options = ["Race", "Sprint"] if "sprint" in str(event.EventFormat).lower() else ["Race"]
    session_name = c3.radio("Session", options, key="lt_session")

    try:
        with st.spinner("Loading lap timing from FastF1. The first load of a race takes up to a minute."):
            laps, results = fd.race_laps(year, int(event.RoundNumber), SESSIONS[session_name])
    except Exception as exc:
        st.error(f"Could not load lap data for this session: {exc}")
        return
    if laps.empty:
        st.info("FastF1 has no lap data for this session.")
        return

    finishers = [d for d in results["Abbreviation"] if d in set(laps["Driver"])]
    chosen = st.multiselect("Drivers", finishers, default=finishers[:5], key="lt_drivers")
    hide = st.toggle("Hide lap 1, pit stops, Safety Car laps and slow laps", value=True)
    if not chosen:
        st.info("Pick at least one driver.")
        return

    clean = clean_laps(laps)
    color, dash = driver_scales(results, chosen)
    base = (clean if hide else laps)
    plot = base[base["Driver"].isin(chosen)].copy()
    plot["Lap time"] = plot["LapSeconds"].map(fmt_lap)
    plot["Line"] = plot["Driver"].map(dash)
    common = {
        "color": alt.Color("Driver:N", scale=color, title=None),
        "strokeDash": alt.StrokeDash("Line:N", legend=None),
    }

    tab_t, tab_p, tab_s = st.tabs(["Lap times", "Positions", "Pace spread"])
    with tab_t:
        if plot.empty:
            st.info("No laps left after filtering. Turn off the filter above.")
        else:
            lo, hi = plot["LapSeconds"].min(), plot["LapSeconds"].max()
            chart = (
                alt.Chart(plot)
                .mark_line(point=alt.OverlayMarkDef(size=18))
                .encode(
                    x=alt.X("LapNumber:Q", title="Lap"),
                    y=alt.Y("LapSeconds:Q", title="Lap time (s)", scale=alt.Scale(domain=[lo - 0.5, hi + 0.5])),
                    tooltip=["Driver", "LapNumber", "Lap time", "Compound", "TyreLife", "Position"],
                    **common,
                )
                .properties(height=440)
            )
            st.altair_chart(chart, width="stretch")
            st.caption("Lower is faster. Gaps in a line are laps hidden by the filter.")
    with tab_p:
        pos = laps[laps["Driver"].isin(chosen)].dropna(subset=["Position"]).copy()
        pos["Line"] = pos["Driver"].map(dash)
        chart = (
            alt.Chart(pos)
            .mark_line()
            .encode(
                x=alt.X("LapNumber:Q", title="Lap"),
                y=alt.Y("Position:Q", scale=alt.Scale(reverse=True, domain=[1, max(20, int(pos["Position"].max() or 20))]), axis=alt.Axis(tickMinStep=1)),
                tooltip=["Driver", "LapNumber", "Position", "Compound"],
                **common,
            )
            .properties(height=440)
        )
        st.altair_chart(chart, width="stretch")
    with tab_s:
        spread = clean[clean["Driver"].isin(chosen)]
        if spread.empty:
            st.info("Not enough clean laps to compare pace.")
        else:
            order = spread.groupby("Driver")["LapSeconds"].median().sort_values().index.tolist()
            chart = (
                alt.Chart(spread)
                .mark_boxplot(extent="min-max", size=28)
                .encode(
                    x=alt.X("Driver:N", sort=order, title=None),
                    y=alt.Y("LapSeconds:Q", title="Clean lap time (s)", scale=alt.Scale(zero=False)),
                    color=alt.Color("Driver:N", scale=color, legend=None),
                )
                .properties(height=440)
            )
            st.altair_chart(chart, width="stretch")
            st.caption("Each box shows a driver's clean laps, fastest median pace on the left. Lap 1, pit laps, Safety Car laps and slow laps are left out.")

    st.subheader("Race summary")
    st.dataframe(summary_table(laps, clean, results), hide_index=True, width="stretch")
