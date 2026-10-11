"""Shared FastF1 helpers. FastF1 downloads timing data from F1's live-timing
service, so everything here is cached twice: on disk by FastF1 (fastf1_cache/
next to app.py) and in memory by Streamlit."""
from datetime import datetime, timezone
from pathlib import Path

import fastf1
import pandas as pd
import streamlit as st

FIRST_FASTF1_SEASON = 2018  # lap timing and telemetry go back to 2018
CACHE_DIR = Path(__file__).resolve().parent.parent / "fastf1_cache"
CACHE_DIR.mkdir(exist_ok=True)
fastf1.Cache.enable_cache(str(CACHE_DIR))


@st.cache_data(ttl=3600, show_spinner=False)
def past_events(year: int) -> pd.DataFrame:
    """Race weekends of `year` whose race has already happened, newest first."""
    sched = fastf1.get_event_schedule(year, include_testing=False)
    now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    race_time = pd.to_datetime(sched["Session5DateUtc"], errors="coerce")
    done = sched[race_time.notna() & (race_time < now - pd.Timedelta(hours=3))]
    cols = ["RoundNumber", "EventName", "Country", "Location", "EventFormat"]
    return pd.DataFrame(done[cols]).sort_values("RoundNumber", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner=False)
def race_laps(year: int, round_number: int, session: str = "R") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (laps, results) for a race ("R") or sprint ("S").

    laps: Driver, LapNumber, LapSeconds, Position, Stint, Compound, TyreLife,
          PitIn, PitOut, Neutralised (SC/VSC/red flag), IsAccurate
    results: Abbreviation, FullName, TeamName, Color (#hex), Position, GridPosition, Status, Points
    """
    s = fastf1.get_session(year, round_number, session)
    s.load(laps=True, telemetry=False, weather=False, messages=False)

    laps = pd.DataFrame(s.laps)
    out = pd.DataFrame(
        {
            "Driver": laps["Driver"],
            "LapNumber": laps["LapNumber"].astype("Int64"),
            "LapSeconds": laps["LapTime"].dt.total_seconds(),
            "Position": laps["Position"],
            "Stint": laps["Stint"],
            "Compound": laps["Compound"].fillna("UNKNOWN"),
            "TyreLife": laps["TyreLife"],
            "PitIn": laps["PitInTime"].notna(),
            "PitOut": laps["PitOutTime"].notna(),
            # Track status codes: 4 = Safety Car, 5 = red flag, 6/7 = Virtual Safety Car.
            "Neutralised": laps["TrackStatus"].fillna("").astype(str).str.contains("[4567]"),
            "IsAccurate": laps["IsAccurate"].fillna(False).astype(bool),
        }
    )

    res = pd.DataFrame(s.results)
    results = pd.DataFrame(
        {
            "Abbreviation": res["Abbreviation"],
            "FullName": res["FullName"],
            "TeamName": res["TeamName"],
            "Color": ("#" + res["TeamColor"].fillna("888888").replace("", "888888").astype(str)),
            "Position": pd.to_numeric(res["Position"], errors="coerce").astype("Int64"),
            "GridPosition": pd.to_numeric(res["GridPosition"], errors="coerce").astype("Int64"),
            "Status": res["Status"],
            "Points": res["Points"],
        }
    ).sort_values("Position", na_position="last").reset_index(drop=True)
    return out, results


def quali_sessions(event_format: str) -> dict[str, str]:
    """Qualifying sessions available at a weekend, label -> FastF1 session name."""
    sessions = {"Qualifying": "Qualifying"}
    fmt = str(event_format).lower()
    if fmt == "sprint_shootout":  # 2023
        sessions["Sprint Shootout"] = "Sprint Shootout"
    elif fmt == "sprint_qualifying":  # 2024 onwards
        sessions["Sprint Qualifying"] = "Sprint Qualifying"
    return sessions


@st.cache_resource(show_spinner=False, max_entries=4)
def _telemetry_session(year: int, round_number: int, session: str):
    s = fastf1.get_session(year, round_number, session)
    s.load(laps=True, telemetry=True, weather=False, messages=False)
    return s


def quali_results(year: int, round_number: int, session: str) -> pd.DataFrame:
    """Abbreviation, FullName, TeamName, Color, Position, Best (fastest lap in seconds)."""
    s = _telemetry_session(year, round_number, session)
    res = pd.DataFrame(s.results)
    best = s.laps.groupby("Driver")["LapTime"].min().dt.total_seconds()
    out = pd.DataFrame(
        {
            "Abbreviation": res["Abbreviation"],
            "FullName": res["FullName"],
            "TeamName": res["TeamName"],
            "Color": "#" + res["TeamColor"].fillna("888888").replace("", "888888").astype(str),
            "Position": pd.to_numeric(res["Position"], errors="coerce").astype("Int64"),
        }
    )
    out["Best"] = out["Abbreviation"].map(best)
    return out.sort_values("Position", na_position="last").reset_index(drop=True)


def fastest_lap_telemetry(year: int, round_number: int, session: str, driver: str) -> tuple[dict, pd.DataFrame]:
    """Telemetry of `driver`'s fastest lap: Distance, Time (s), Speed, Throttle,
    Brake (0/1), Gear, X, Y. Also returns lap info (LapSeconds, Compound)."""
    s = _telemetry_session(year, round_number, session)
    lap = s.laps.pick_drivers(driver).pick_fastest()
    if lap is None or pd.isna(lap.get("LapTime")):
        raise ValueError(f"{driver} has no timed lap in this session")
    tel = lap.get_telemetry()
    out = pd.DataFrame(
        {
            "Distance": tel["Distance"].to_numpy(),
            "Time": tel["Time"].dt.total_seconds().to_numpy(),
            "Speed": tel["Speed"].to_numpy(),
            "Throttle": tel["Throttle"].to_numpy(),
            "Brake": tel["Brake"].astype(float).to_numpy(),
            "Gear": tel["nGear"].to_numpy(),
            "X": tel["X"].to_numpy(),
            "Y": tel["Y"].to_numpy(),
        }
    )
    info = {"LapSeconds": lap["LapTime"].total_seconds(), "Compound": lap.get("Compound")}
    return info, out


def corners(year: int, round_number: int, session: str) -> pd.DataFrame:
    """Corner numbers and their distance from the start line, if FastF1 has them."""
    try:
        ci = _telemetry_session(year, round_number, session).get_circuit_info()
        c = ci.corners
        return pd.DataFrame({"Corner": c["Number"].astype(str) + c["Letter"].fillna(""), "Distance": c["Distance"]})
    except Exception:
        return pd.DataFrame(columns=["Corner", "Distance"])
