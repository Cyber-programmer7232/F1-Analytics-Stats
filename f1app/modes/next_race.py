"""Mode 1: Next race. Shows the upcoming Grand Prix, its sessions in your
timezone, a countdown, the circuit on a map, and the season calendar."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

import pandas as pd
import streamlit as st

from f1app import jolpica

# Session keys as they appear in jolpica race objects, in weekend order.
# Sprint qualifying was called "SprintShootout" in 2023.
SESSIONS = [
    ("FirstPractice", "Practice 1"),
    ("SecondPractice", "Practice 2"),
    ("ThirdPractice", "Practice 3"),
    ("SprintQualifying", "Sprint Qualifying"),
    ("SprintShootout", "Sprint Shootout"),
    ("Sprint", "Sprint"),
    ("Qualifying", "Qualifying"),
]


def parse_utc(date: str, time: str | None) -> datetime | None:
    """jolpica gives date "2026-10-25" and time "19:00:00Z"; time can be missing."""
    if not date:
        return None
    if not time:
        return datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(f"{date}T{time.replace('Z', '')}").replace(tzinfo=timezone.utc)


def weekend_sessions(race: dict) -> list[tuple[str, datetime | None]]:
    sessions = [
        (label, parse_utc(race[key].get("date"), race[key].get("time")))
        for key, label in SESSIONS
        if key in race
    ]
    sessions.append(("Race", parse_utc(race.get("date"), race.get("time"))))
    return sessions


def find_next_race(now: datetime) -> tuple[dict | None, list[dict]]:
    """Return the next race (or None) and the current season's calendar.

    Uses the full calendar rather than /current/next so a race that is under
    way still counts as "next" until it has finished (about 3 hours)."""
    calendar = jolpica.races("current")
    for race in calendar:
        start = parse_utc(race["date"], race.get("time"))
        if start and start.timestamp() + 3 * 3600 > now.timestamp():
            return race, calendar
    # Season over: try the first race of next season.
    if calendar:
        upcoming = jolpica.races(f"{int(calendar[0]['season']) + 1}")
        if upcoming:
            return upcoming[0], calendar
    return None, calendar


def format_countdown(delta_seconds: float) -> str:
    if delta_seconds <= 0:
        return "Under way"
    days, rem = divmod(int(delta_seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h {minutes}m"


def render():
    st.header("🏁 Next race")

    zones = sorted(available_timezones())
    tz_name = st.selectbox(
        "Show times in", zones, index=zones.index("UTC") if "UTC" in zones else 0
    )
    tz = ZoneInfo(tz_name)
    now = datetime.now(timezone.utc)

    try:
        race, calendar = find_next_race(now)
    except jolpica.JolpicaError as exc:
        st.error(str(exc))
        return

    if race is None:
        st.info("No upcoming race is scheduled yet. Check back when the next calendar is published.")
        return

    circuit = race["Circuit"]
    location = circuit["Location"]
    race_start = parse_utc(race["date"], race.get("time"))

    st.subheader(f"{race['season']} {race['raceName']}")
    st.caption(f"Round {race['round']} · {circuit['circuitName']} · {location['locality']}, {location['country']}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Starts in", format_countdown((race_start - now).total_seconds()) if race_start else "TBC")
    c2.metric("Race day", race_start.astimezone(tz).strftime("%a %d %b") if race_start else race["date"])
    c3.metric("Sprint weekend", "Yes" if "Sprint" in race else "No")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Weekend schedule**")
        rows = [
            {
                "Session": label,
                "Day": start.astimezone(tz).strftime("%a %d %b") if start else "TBC",
                "Time": start.astimezone(tz).strftime("%H:%M") if start else "TBC",
                "Status": "Done" if start and start < now else "Upcoming",
            }
            for label, start in weekend_sessions(race)
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with right:
        st.markdown("**Circuit**")
        st.map(
            pd.DataFrame({"lat": [float(location["lat"])], "lon": [float(location["long"])]}),
            zoom=4,
        )
        if circuit.get("url"):
            st.markdown(f"[About this circuit]({circuit['url']})")

    with st.expander(f"Full {calendar[0]['season'] if calendar else ''} calendar"):
        rows = []
        for r in calendar:
            start = parse_utc(r["date"], r.get("time"))
            rows.append(
                {
                    "Round": int(r["round"]),
                    "Grand Prix": r["raceName"],
                    "Circuit": r["Circuit"]["circuitName"],
                    "Date": start.astimezone(tz).strftime("%d %b %H:%M") if start else r["date"],
                    "Sprint": "✓" if "Sprint" in r else "",
                    "Done": "✓" if start and start.timestamp() + 3 * 3600 < now.timestamp() else "",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
