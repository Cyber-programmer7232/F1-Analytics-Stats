"""Mode 7: Tyre strategy (FastF1). Every driver's stints in a race as a
bar per driver, the strategies used, and how lap time changed as tyres wore."""
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from f1app import fastf1_data as fd
from f1app.modes.lap_times import SESSIONS, clean_laps, fmt_lap

COMPOUND_COLORS = {
    "SOFT": "#DA291C",
    "MEDIUM": "#FFD12E",
    "HARD": "#C8C8C8",
    "INTERMEDIATE": "#43B02A",
    "WET": "#0067AD",
    "UNKNOWN": "#8C8C8C",
    "TEST_UNKNOWN": "#8C8C8C",
}


def compound_scale(compounds) -> alt.Scale:
    order = [c for c in COMPOUND_COLORS if c in set(compounds)]
    return alt.Scale(domain=order, range=[COMPOUND_COLORS[c] for c in order])


def stints(laps: pd.DataFrame) -> pd.DataFrame:
    """One row per driver stint: Driver, Stint, Compound, Start, End, Laps, StartTyreLife."""
    s = laps.dropna(subset=["Stint"])
    out = (
        s.groupby(["Driver", "Stint"])
        .agg(
            Compound=("Compound", lambda c: c.mode().iat[0] if not c.mode().empty else "UNKNOWN"),
            Start=("LapNumber", "min"),
            End=("LapNumber", "max"),
            StartTyreLife=("TyreLife", "min"),
        )
        .reset_index()
    )
    out["Laps"] = (out["End"] - out["Start"] + 1).astype(int)
    out["Start"] = out["Start"].astype(int)
    out["End"] = out["End"].astype(int)
    # Tyres that already had laps on them when fitted were used (e.g. from qualifying).
    out["Tyres"] = out["StartTyreLife"].apply(lambda t: "Used" if pd.notna(t) and t > 1 else "New")
    return out.sort_values(["Driver", "Stint"])


def strategy_label(driver_stints: pd.DataFrame) -> str:
    return " → ".join(c.title() for c in driver_stints.sort_values("Stint")["Compound"])


def render():
    st.header("🛞 Tyre strategy")
    now_year = datetime.now(timezone.utc).year

    c1, c2, c3 = st.columns([1, 3, 1])
    year = c1.selectbox("Season", list(range(now_year, fd.FIRST_FASTF1_SEASON - 1, -1)), key="ts_year")
    try:
        events = fd.past_events(year)
    except Exception as exc:
        st.error(f"Could not load the {year} schedule: {exc}")
        return
    if events.empty:
        st.info(f"No {year} races have happened yet.")
        return
    labels = {f"R{r.RoundNumber} · {r.EventName}": r for r in events.itertuples()}
    event = labels[c2.selectbox("Race", list(labels), key="ts_event")]
    options = ["Race", "Sprint"] if "sprint" in str(event.EventFormat).lower() else ["Race"]
    session_name = c3.radio("Session", options, key="ts_session")

    try:
        with st.spinner("Loading lap timing from FastF1. The first load of a race takes up to a minute."):
            laps, results = fd.race_laps(year, int(event.RoundNumber), SESSIONS[session_name])
    except Exception as exc:
        st.error(f"Could not load lap data for this session: {exc}")
        return
    st_df = stints(laps)
    if st_df.empty:
        st.info("FastF1 has no tyre data for this session.")
        return

    order = [d for d in results["Abbreviation"] if d in set(st_df["Driver"])]
    order += [d for d in st_df["Driver"].unique() if d not in order]
    st_df["Finish"] = st_df["Driver"].map({d: i + 1 for i, d in enumerate(order)})
    scale = compound_scale(st_df["Compound"])

    # Strategy summary
    strategies = st_df.groupby("Driver").apply(strategy_label, include_groups=False)
    stops = st_df.groupby("Driver")["Stint"].count() - 1
    m1, m2, m3 = st.columns(3)
    winner = order[0]
    m1.metric("Winner's strategy", strategies.get(winner, "–"), winner, delta_color="off")
    m2.metric("Most common number of stops", int(stops.mode().iat[0]))
    longest = st_df.loc[st_df["Laps"].idxmax()]
    m3.metric("Longest stint", f"{longest['Laps']} laps", f"{longest['Driver']} · {longest['Compound'].title()}", delta_color="off")

    st.subheader("Stints")
    bars = (
        alt.Chart(st_df)
        .mark_bar(stroke="#333333", strokeWidth=0.6, cornerRadius=2)
        .encode(
            y=alt.Y("Driver:N", sort=order, title=None),
            x=alt.X("Start:Q", title="Lap", scale=alt.Scale(domain=[0, int(st_df["End"].max()) + 1])),
            x2=alt.X2("EndPlus:Q"),
            color=alt.Color("Compound:N", scale=scale, title="Compound"),
            opacity=alt.Opacity("Tyres:N", scale=alt.Scale(domain=["New", "Used"], range=[1.0, 0.55]), title="Tyres"),
            tooltip=["Driver", "Stint", "Compound", "Tyres", "Start", "End", "Laps"],
        )
        .transform_calculate(EndPlus="datum.End + 1")
        .properties(height=max(260, 24 * len(order)))
    )
    st.altair_chart(bars, width="stretch")
    st.caption("Drivers are in finishing order. Faded bars are stints started on used tyres.")

    with st.expander("Strategies used"):
        table = (
            pd.DataFrame({"Strategy": strategies, "Stops": stops})
            .reset_index()
            .groupby(["Strategy", "Stops"])["Driver"]
            .apply(lambda d: ", ".join(sorted(d, key=order.index)))
            .reset_index()
        )
        table["Drivers"] = table["Driver"].str.count(",") + 1
        st.dataframe(table[["Strategy", "Stops", "Drivers", "Driver"]].rename(columns={"Driver": "Who"}).sort_values("Drivers", ascending=False),
                     hide_index=True, width="stretch")

    st.subheader("Tyre wear")
    clean = clean_laps(laps).dropna(subset=["TyreLife"])
    if clean.empty:
        st.info("Not enough clean laps to show tyre wear.")
        return
    chosen = st.multiselect("Drivers", order, default=order[:10], key="ts_drivers")
    wear = clean[clean["Driver"].isin(chosen)].copy()
    if wear.empty:
        st.info("Pick at least one driver.")
        return
    wear["Lap time"] = wear["LapSeconds"].map(fmt_lap)
    points = (
        alt.Chart(wear)
        .mark_circle(size=28, opacity=0.55, stroke="#333333", strokeWidth=0.3)
        .encode(
            x=alt.X("TyreLife:Q", title="Tyre age (laps)"),
            y=alt.Y("LapSeconds:Q", title="Clean lap time (s)", scale=alt.Scale(zero=False)),
            color=alt.Color("Compound:N", scale=compound_scale(wear["Compound"]), title="Compound"),
            tooltip=["Driver", "LapNumber", "Lap time", "Compound", "TyreLife"],
        )
    )
    trend = (
        alt.Chart(wear)
        .transform_regression("TyreLife", "LapSeconds", groupby=["Compound"])
        .mark_line(strokeWidth=3)
        .encode(x="TyreLife:Q", y="LapSeconds:Q", color=alt.Color("Compound:N", scale=compound_scale(wear["Compound"])))
    )
    st.altair_chart((points + trend).properties(height=400), width="stretch")

    # Seconds lost per lap of tyre age, per compound (slope of a straight-line fit).
    rows = []
    for comp, g in wear.groupby("Compound"):
        if g["TyreLife"].nunique() >= 3:
            slope = pd.Series(g["LapSeconds"].values).cov(pd.Series(g["TyreLife"].values)) / g["TyreLife"].var()
            rows.append({"Compound": comp.title(), "Seconds lost per lap of wear": round(slope, 3), "Clean laps": len(g)})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Each dot is a clean lap. Lines are straight-line trends per compound. Fuel burning off makes cars faster as the race goes on, "
        "so real tyre wear is a bit larger than these lines suggest."
    )
