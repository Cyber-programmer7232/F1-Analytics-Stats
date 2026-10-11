"""Mode 3: Points race. How the championship unfolded round by round:
cumulative points, gap to the leader, or championship position."""
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from f1app import jolpica
from f1app.modes.standings import (
    FIRST_CONSTRUCTORS_SEASON,
    FIRST_SEASON,
    constructor_table,
    driver_table,
)

VIEWS = {
    "Points": ("Points", "Championship points"),
    "Gap to leader": ("Gap", "Points behind the leader"),
    "Championship position": ("PosNum", "Position"),
}


def short_name(race_name: str) -> str:
    return race_name.replace(" Grand Prix", " GP")


def progression(season: int, kind: str) -> pd.DataFrame:
    """Standings after every completed round, as one long table:
    Round, Race, Name, Points, Gap, PosNum. Uses the per-round standings
    endpoint so dropped scores and penalties match the official tables."""
    latest = jolpica.standings(str(season), kind)
    if latest is None:
        return pd.DataFrame()
    last_round = int(latest["round"])
    names = {int(r["round"]): short_name(r["raceName"]) for r in jolpica.races(str(season))}

    label = "Driver" if kind == "driver" else "Team"
    frames = []
    progress = st.progress(0.0, text="Loading round-by-round standings…")
    for rnd in range(1, last_round + 1):
        lst = latest if rnd == last_round else jolpica.standings(str(season), kind, rnd)
        progress.progress(rnd / last_round, text=f"Loading round {rnd} of {last_round}…")
        if lst is None:
            continue
        df = (
            driver_table(lst["DriverStandings"])
            if kind == "driver"
            else constructor_table(lst["ConstructorStandings"])
        )
        df = df.rename(columns={label: "Name"})[["Name", "Pos", "Points", "Gap"]]
        df["Round"] = rnd
        df["Race"] = names.get(rnd, f"Round {rnd}")
        frames.append(df)
    progress.empty()
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["PosNum"] = pd.to_numeric(out["Pos"], errors="coerce")
    return out


def render():
    st.header("📈 Points race")
    now_year = datetime.now(timezone.utc).year

    c1, c2, c3 = st.columns([1, 1, 2])
    season = c1.selectbox("Season", list(range(now_year, FIRST_SEASON - 1, -1)), key="pr_season")
    kinds = ["Drivers", "Constructors"] if season >= FIRST_CONSTRUCTORS_SEASON else ["Drivers"]
    kind_label = c2.radio("Championship", kinds, horizontal=True)
    view = c3.radio("Show", list(VIEWS), horizontal=True)
    kind = "driver" if kind_label == "Drivers" else "constructor"

    try:
        data = progression(season, kind)
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return
    if data.empty:
        st.info(f"No standings for {season} yet. The season may not have started.")
        return

    last_round = data["Round"].max()
    final = data[data["Round"] == last_round].sort_values("Points", ascending=False)
    ordered = final["Name"].tolist()
    default_n = 10 if kind == "driver" else 6
    chosen = st.multiselect(
        "Show these (ordered by latest standings)", ordered, default=ordered[:default_n]
    )
    if not chosen:
        st.info("Pick at least one name to draw the chart.")
        return

    field, axis_title = VIEWS[view]
    plot = data[data["Name"].isin(chosen)].dropna(subset=[field])
    race_order = data.drop_duplicates("Round").sort_values("Round")["Race"].tolist()

    y = alt.Y(f"{field}:Q", title=axis_title)
    if field == "PosNum":
        y = alt.Y("PosNum:Q", title=axis_title, scale=alt.Scale(reverse=True, zero=False), axis=alt.Axis(tickMinStep=1))

    chart = (
        alt.Chart(plot)
        .mark_line(point=True)
        .encode(
            x=alt.X("Race:N", sort=race_order, title=None, axis=alt.Axis(labelAngle=-45)),
            y=y,
            color=alt.Color("Name:N", sort=chosen, title=None),
            tooltip=["Race", "Name", "Pos", "Points", "Gap"],
        )
        .properties(height=480)
    )
    st.altair_chart(chart, width="stretch")

    # Biggest single-round points haul among the chosen names.
    gains = plot.sort_values("Round").copy()
    gains["Gained"] = gains.groupby("Name")["Points"].diff().fillna(gains["Points"])
    best = gains.loc[gains["Gained"].idxmax()]
    leaders = data[data["PosNum"] == 1].drop_duplicates("Round")
    m1, m2 = st.columns(2)
    m1.metric("Biggest single-round haul", f"{best['Gained']:g} pts", f"{best['Name']} · {best['Race']}", delta_color="off")
    m2.metric("Different leaders this season", leaders["Name"].nunique())

    with st.expander("Data table"):
        table = data[data["Name"].isin(chosen)].pivot_table(
            index="Name", columns="Round", values="Points", aggfunc="first"
        ).reindex(chosen)
        st.dataframe(table, width="stretch")
