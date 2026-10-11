"""Mode 2: Standings. Driver and constructor championship tables for any
season, optionally as they stood after a chosen round."""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from f1app import jolpica

FIRST_SEASON = 1950
FIRST_CONSTRUCTORS_SEASON = 1958  # the constructors' title started in 1958


def _position(entry: dict, fallback: int) -> str:
    # "position" is missing for excluded drivers (e.g. Schumacher 1997); positionText says why.
    text = entry.get("positionText", "")
    if "position" not in entry:
        return {"D": "DSQ", "E": "EXC", "-": "–"}.get(text, text or str(fallback))
    return entry["position"]


def driver_table(entries: list[dict]) -> pd.DataFrame:
    rows = []
    for i, e in enumerate(entries, start=1):
        d = e["Driver"]
        rows.append(
            {
                "Pos": _position(e, i),
                "Driver": f"{d['givenName']} {d['familyName']}",
                "Code": d.get("code", ""),
                "Nationality": d.get("nationality", ""),
                "Team": ", ".join(c["name"] for c in e.get("Constructors", [])),
                "Points": float(e["points"]),
                "Wins": int(e["wins"]),
            }
        )
    return _add_gap(pd.DataFrame(rows))


def constructor_table(entries: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "Pos": _position(e, i),
            "Team": e["Constructor"]["name"],
            "Nationality": e["Constructor"].get("nationality", ""),
            "Points": float(e["points"]),
            "Wins": int(e["wins"]),
        }
        for i, e in enumerate(entries, start=1)
    ]
    return _add_gap(pd.DataFrame(rows))


def _add_gap(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df["Gap"] = df["Points"].iloc[0] - df["Points"]
    # Show 25.0 as 25 but keep half points (e.g. 12.5) as they are.
    for col in ("Points", "Gap"):
        if (df[col] % 1 == 0).all():
            df[col] = df[col].astype(int)
    return df


def _show(df: pd.DataFrame, label_col: str, top_n: int):
    st.dataframe(df, hide_index=True, width="stretch")
    top = df.head(top_n).set_index(label_col)["Points"]
    st.markdown(f"**Points, top {min(top_n, len(df))}**")
    st.bar_chart(top.sort_values(), horizontal=True, height=max(250, 28 * len(top)))


def render():
    st.header("🏆 Standings")
    now_year = datetime.now(timezone.utc).year

    c1, c2 = st.columns([1, 2])
    season = c1.selectbox("Season", list(range(now_year, FIRST_SEASON - 1, -1)))

    try:
        latest = jolpica.standings(str(season), "driver")
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return
    if latest is None:
        st.info(f"No standings for {season} yet. The season may not have started.")
        return

    last_round = int(latest["round"])
    try:
        total_rounds = len(jolpica.races(str(season)))
    except jolpica.JolpicaError:
        total_rounds = last_round
    finished = last_round >= total_rounds

    round_ = last_round
    if last_round > 1:
        round_ = c2.slider("After round", 1, last_round, last_round)

    try:
        drivers = latest if round_ == last_round else jolpica.standings(str(season), "driver", round_)
        teams = (
            jolpica.standings(str(season), "constructor", round_)
            if season >= FIRST_CONSTRUCTORS_SEASON
            else None
        )
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return

    driver_df = driver_table(drivers["DriverStandings"]) if drivers else pd.DataFrame()
    team_df = constructor_table(teams["ConstructorStandings"]) if teams else pd.DataFrame()

    status = "Final standings" if finished and round_ == last_round else f"After round {round_} of {total_rounds}"
    st.caption(status)

    m1, m2, m3 = st.columns(3)
    if not driver_df.empty:
        leader = driver_df.iloc[0]
        title = "Champion" if finished and round_ == last_round else "Leader"
        m1.metric(f"Drivers' {title}", leader["Driver"], f"{leader['Points']} pts", delta_color="off")
        if len(driver_df) > 1:
            m2.metric("Gap to P2", f"{driver_df.iloc[1]['Gap']} pts", driver_df.iloc[1]["Driver"], delta_color="off")
    if not team_df.empty:
        t = team_df.iloc[0]
        title = "Champion" if finished and round_ == last_round else "Leader"
        m3.metric(f"Constructors' {title}", t["Team"], f"{t['Points']} pts", delta_color="off")

    tab_d, tab_c = st.tabs(["Drivers", "Constructors"])
    with tab_d:
        if driver_df.empty:
            st.info("No driver standings for this round.")
        else:
            _show(driver_df, "Driver", 20)
    with tab_c:
        if season < FIRST_CONSTRUCTORS_SEASON:
            st.info("The constructors' championship began in 1958, so there is no team table for this season.")
        elif team_df.empty:
            st.info("No constructor standings for this round.")
        else:
            _show(team_df, "Team", 12)
