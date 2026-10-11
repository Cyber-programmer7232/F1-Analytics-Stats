"""Mode 8: Season dashboard. One page per season: championship leaders,
standings, the points race and every race winner from jolpica-f1, plus a
FastF1 deep dive into any race from 2018 onwards."""
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from f1app import jolpica
from f1app.modes.lap_times import SESSIONS, clean_laps, fmt_lap
from f1app.modes.points_race import progression
from f1app.modes.standings import FIRST_CONSTRUCTORS_SEASON, FIRST_SEASON, constructor_table, driver_table
from f1app.modes.tyre_strategy import compound_scale, stints


def winners_table(season: int) -> pd.DataFrame:
    """Round, Grand Prix, Winner, Team, Started (grid slot), Pole."""
    wins = jolpica.all_races(f"{season}/results/1")
    poles = {
        r["round"]: ", ".join(f"{x['Driver']['givenName']} {x['Driver']['familyName']}" for x in r.get("Results", []))
        for r in jolpica.all_races(f"{season}/grid/1/results")
    }
    rows = []
    for r in wins:
        for res in r.get("Results", []):
            d = res["Driver"]
            rows.append(
                {
                    "Round": int(r["round"]),
                    "Grand Prix": r["raceName"].replace(" Grand Prix", " GP"),
                    "Winner": f"{d['givenName']} {d['familyName']}",
                    "Team": res["Constructor"]["name"],
                    "Started": res.get("grid", ""),
                    "Pole": poles.get(r["round"], ""),
                }
            )
    return pd.DataFrame(rows).sort_values("Round") if rows else pd.DataFrame()


def overview(season: int):
    try:
        drivers = jolpica.standings(str(season), "driver")
        teams = jolpica.standings(str(season), "constructor") if season >= FIRST_CONSTRUCTORS_SEASON else None
        total_rounds = len(jolpica.races(str(season)))
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return
    if drivers is None:
        st.info(f"No standings for {season} yet. The season may not have started.")
        return

    done = int(drivers["round"])
    finished = done >= total_rounds
    driver_df = driver_table(drivers["DriverStandings"])
    team_df = constructor_table(teams["ConstructorStandings"]) if teams else pd.DataFrame()
    title = "Champion" if finished else "Leader"

    try:
        winners = winners_table(season)
    except jolpica.JolpicaError as exc:
        winners = pd.DataFrame()
        st.warning(f"Could not load race winners: {exc}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rounds", f"{done} / {total_rounds}", "Season finished" if finished else "In progress", delta_color="off")
    lead = driver_df.iloc[0]
    gap = f"+{driver_df.iloc[1]['Gap']} pts over {driver_df.iloc[1]['Driver']}" if len(driver_df) > 1 else None
    m2.metric(f"Drivers' {title.lower()}", lead["Driver"], gap, delta_color="off")
    if not team_df.empty:
        m3.metric(f"Constructors' {title.lower()}", team_df.iloc[0]["Team"], f"{team_df.iloc[0]['Points']} pts", delta_color="off")
    if not winners.empty:
        m4.metric("Different winners", winners["Winner"].nunique(), f"{winners['Team'].nunique()} teams", delta_color="off")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Points race, top 6**")
        data = progression(season, "driver")
        if not data.empty:
            top = data[data["Round"] == data["Round"].max()].nlargest(6, "Points")["Name"].tolist()
            race_order = data.drop_duplicates("Round").sort_values("Round")["Race"].tolist()
            chart = (
                alt.Chart(data[data["Name"].isin(top)])
                .mark_line(point=True)
                .encode(
                    x=alt.X("Race:N", sort=race_order, title=None, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("Points:Q"),
                    color=alt.Color("Name:N", sort=top, title=None),
                    tooltip=["Race", "Name", "Pos", "Points"],
                )
                .properties(height=340)
            )
            st.altair_chart(chart, width="stretch")
    with right:
        tab_d, tab_c = st.tabs(["Drivers", "Constructors"])
        with tab_d:
            st.dataframe(driver_df[["Pos", "Driver", "Team", "Points", "Wins"]].head(10), hide_index=True, width="stretch")
        with tab_c:
            if team_df.empty:
                st.info("No constructors' championship this season.")
            else:
                st.dataframe(team_df[["Pos", "Team", "Points", "Wins"]], hide_index=True, width="stretch")

    if not winners.empty:
        st.markdown("**Race by race**")
        w1, w2 = st.columns([3, 2])
        w1.dataframe(winners, hide_index=True, width="stretch", height=min(420, 36 * (len(winners) + 1)))
        by_team = winners.groupby("Team").size().reset_index(name="Wins")
        w2.altair_chart(
            alt.Chart(by_team)
            .mark_arc(innerRadius=55)
            .encode(theta="Wins:Q", color=alt.Color("Team:N", title=None), tooltip=["Team", "Wins"])
            .properties(height=300, title="Wins by team"),
            width="stretch",
        )


def deep_dive(season: int):
    from f1app import fastf1_data as fd

    if season < fd.FIRST_FASTF1_SEASON:
        st.info(f"FastF1 lap data starts in {fd.FIRST_FASTF1_SEASON}. Pick a later season for race deep dives.")
        return
    try:
        events = fd.past_events(season)
    except Exception as exc:
        st.error(f"Could not load the {season} schedule: {exc}")
        return
    if events.empty:
        st.info(f"No {season} races have happened yet.")
        return
    labels = {f"R{r.RoundNumber} · {r.EventName}": r for r in events.itertuples()}
    event = labels[st.selectbox("Race", list(labels), key="db_event")]
    try:
        with st.spinner("Loading lap timing from FastF1. The first load of a race takes up to a minute."):
            laps, results = fd.race_laps(season, int(event.RoundNumber), SESSIONS["Race"])
    except Exception as exc:
        st.error(f"Could not load lap data for this race: {exc}")
        return
    if laps.empty or results.empty:
        st.info("FastF1 has no lap data for this race.")
        return

    podium = results.head(3)
    cols = st.columns(4)
    for col, (medal, r) in zip(cols, zip(["🥇", "🥈", "🥉"], podium.itertuples())):
        col.metric(f"{medal} P{r.Position}", r.FullName, f"{r.TeamName} · from P{r.GridPosition}", delta_color="off")
    fastest = laps.loc[laps["LapSeconds"].idxmin()]
    cols[3].metric("Fastest lap", fmt_lap(fastest["LapSeconds"]), f"{fastest['Driver']} · lap {fastest['LapNumber']}", delta_color="off")

    top5 = [d for d in results["Abbreviation"].head(5) if d in set(laps["Driver"])]
    info = results.set_index("Abbreviation")
    colors = alt.Scale(domain=top5, range=[info.loc[d, "Color"] for d in top5])
    left, right = st.columns(2)
    with left:
        st.markdown("**Top 5 lap times (clean laps)**")
        clean = clean_laps(laps)
        plot = clean[clean["Driver"].isin(top5)]
        if plot.empty:
            st.info("Not enough clean laps.")
        else:
            st.altair_chart(
                alt.Chart(plot)
                .mark_line(point=alt.OverlayMarkDef(size=14))
                .encode(
                    x=alt.X("LapNumber:Q", title="Lap"),
                    y=alt.Y("LapSeconds:Q", title="Lap time (s)", scale=alt.Scale(zero=False)),
                    color=alt.Color("Driver:N", scale=colors, title=None),
                    tooltip=["Driver", "LapNumber", "Compound"],
                )
                .properties(height=360),
                width="stretch",
            )
    with right:
        st.markdown("**Tyre strategies, top 10**")
        s = stints(laps)
        top10 = [d for d in results["Abbreviation"].head(10) if d in set(s["Driver"])]
        s = s[s["Driver"].isin(top10)].assign(EndPlus=lambda d: d["End"] + 1)
        if s.empty:
            st.info("No tyre data.")
        else:
            st.altair_chart(
                alt.Chart(s)
                .mark_bar(stroke="#333333", strokeWidth=0.6)
                .encode(
                    y=alt.Y("Driver:N", sort=top10, title=None),
                    x=alt.X("Start:Q", title="Lap"),
                    x2="EndPlus:Q",
                    color=alt.Color("Compound:N", scale=compound_scale(s["Compound"]), title=None),
                    tooltip=["Driver", "Compound", "Start", "End", "Laps"],
                )
                .properties(height=360),
                width="stretch",
            )
    st.caption("For the full detail of this race, open modes 5 and 7.")


def render():
    st.header("🗂️ Season dashboard")
    now_year = datetime.now(timezone.utc).year
    season = st.selectbox("Season", list(range(now_year, FIRST_SEASON - 1, -1)), key="db_season")
    # A radio rather than tabs, so the slow FastF1 load only runs when asked for.
    view = st.radio("View", ["Season overview", "Race deep dive"], horizontal=True, label_visibility="collapsed")
    if view == "Season overview":
        overview(season)
    else:
        deep_dive(season)
