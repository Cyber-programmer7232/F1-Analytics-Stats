"""Mode 4: All-time stats. Leaderboards for wins, podiums, poles and
championships since 1950, filterable by era, with a season-by-season view."""
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from f1app import jolpica
from f1app.modes.standings import FIRST_CONSTRUCTORS_SEASON, FIRST_SEASON

# Stat label -> jolpica paths whose rows each count as one.
RESULT_STATS = {
    "Wins": ["results/1"],
    "Podiums": ["results/1", "results/2", "results/3"],
    "Poles": ["grid/1/results"],
}
TITLES = "Championships"
STATS = list(RESULT_STATS) + [TITLES]


@st.cache_data(ttl=86400, show_spinner=False)
def load_results(path: str) -> pd.DataFrame:
    """One row per result: Season, Round, Race, Driver, Team."""
    rows = []
    for race in jolpica.all_races(path):
        for r in race.get("Results", []):
            d, c = r["Driver"], r["Constructor"]
            rows.append(
                {
                    "Season": int(race["season"]),
                    "Round": int(race["round"]),
                    "Race": race["raceName"],
                    "Driver": f"{d['givenName']} {d['familyName']}",
                    "Team": c["name"],
                }
            )
    return pd.DataFrame(rows, columns=["Season", "Round", "Race", "Driver", "Team"])


@st.cache_data(ttl=86400, show_spinner=False)
def load_titles(kind: str) -> pd.DataFrame:
    """One row per championship: Season, Name. Leaves out a season still in progress."""
    data = jolpica.get(f"{kind}standings/1")
    key = "DriverStandings" if kind == "driver" else "ConstructorStandings"
    current_year = datetime.now(timezone.utc).year
    rows = []
    for lst in data["StandingsTable"]["StandingsLists"]:
        season = int(lst["season"])
        if season >= current_year and int(lst["round"]) < len(jolpica.races(str(season))):
            continue  # not decided yet
        for e in lst[key]:
            if kind == "driver":
                name = f"{e['Driver']['givenName']} {e['Driver']['familyName']}"
            else:
                name = e["Constructor"]["name"]
            rows.append({"Season": season, "Name": name})
    return pd.DataFrame(rows, columns=["Season", "Name"])


def stat_rows(stat: str, who: str) -> pd.DataFrame:
    """Rows of (Season, Name), one per counted win/podium/pole/title."""
    if stat == TITLES:
        return load_titles("driver" if who == "Drivers" else "constructor")
    frames = [load_results(p) for p in RESULT_STATS[stat]]
    df = pd.concat(frames, ignore_index=True)
    col = "Driver" if who == "Drivers" else "Team"
    return df.rename(columns={col: "Name"})[["Season", "Name"]]


def render():
    st.header("📊 All-time stats")
    now_year = datetime.now(timezone.utc).year

    c1, c2 = st.columns([1, 2])
    who = c1.radio("Who", ["Drivers", "Constructors"], horizontal=True)
    stat = c2.radio("Stat", STATS, horizontal=True)
    c3, c4 = st.columns([3, 1])
    first = FIRST_CONSTRUCTORS_SEASON if who == "Constructors" and stat == TITLES else FIRST_SEASON
    era = c3.slider("Seasons", first, now_year, (first, now_year))
    top_n = c4.number_input("Show top", 5, 50, 15, step=5)

    try:
        with st.spinner(f"Loading every {stat.lower()} since 1950 (first time only)…"):
            rows = stat_rows(stat, who)
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return

    rows = rows[(rows["Season"] >= era[0]) & (rows["Season"] <= era[1])]
    if rows.empty:
        st.info("Nothing to show for these seasons.")
        return

    board = (
        rows.groupby("Name")
        .agg(Count=("Season", "size"), First=("Season", "min"), Last=("Season", "max"))
        .sort_values(["Count", "First"], ascending=[False, True])
        .reset_index()
    )
    board.insert(0, "Rank", board["Count"].rank(method="min", ascending=False).astype(int))
    top = board.head(int(top_n))

    m1, m2, m3 = st.columns(3)
    m1.metric(f"Most {stat.lower()}", top.iloc[0]["Name"], f"{top.iloc[0]['Count']}", delta_color="off")
    m2.metric(f"Total {stat.lower()} in range", int(board["Count"].sum()))
    m3.metric(f"Different {who.lower()} with at least one", len(board))

    chart = (
        alt.Chart(top)
        .mark_bar()
        .encode(
            x=alt.X("Count:Q", title=stat),
            y=alt.Y("Name:N", sort="-x", title=None),
            tooltip=["Rank", "Name", "Count", "First", "Last"],
        )
        .properties(height=max(250, 26 * len(top)))
    )
    st.altair_chart(chart, width="stretch")
    with st.expander("Full table"):
        st.dataframe(
            board.rename(columns={"Count": stat, "First": "First season", "Last": "Last season"}),
            hide_index=True,
            width="stretch",
        )
    if stat == "Poles":
        st.caption("Poles are counted as starting the race from P1, which can differ from qualifying pole after grid penalties.")

    st.subheader("Season by season")
    names = board["Name"].tolist()
    chosen = st.multiselect("Compare", names, default=names[:3], max_selections=6)
    if chosen:
        per_season = (
            rows[rows["Name"].isin(chosen)]
            .groupby(["Season", "Name"])
            .size()
            .reset_index(name="Count")
        )
        per_season["Running total"] = per_season.sort_values("Season").groupby("Name")["Count"].cumsum()
        view = st.radio("Show", ["Per season", "Running total"], horizontal=True)
        field = "Count" if view == "Per season" else "Running total"
        mark = alt.Chart(per_season).mark_bar() if view == "Per season" else alt.Chart(per_season).mark_line(point=True)
        enc = {
            "x": alt.X("Season:O", title=None),
            "y": alt.Y(f"{field}:Q", title=stat),
            "color": alt.Color("Name:N", sort=chosen, title=None),
            "tooltip": ["Season", "Name", "Count", "Running total"],
        }
        if view == "Per season":
            enc["xOffset"] = alt.XOffset("Name:N", sort=chosen)
        st.altair_chart(mark.encode(**enc).properties(height=380), width="stretch")
