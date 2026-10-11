"""Small client for the jolpica-f1 (Ergast-compatible) API.

Every mode goes through `get()`, which caches responses for an hour and spaces
requests out so we stay under jolpica's rate limits (4 req/s burst, 500 req/hour).
"""
import threading
import time

import requests
import streamlit as st

BASE_URL = "https://api.jolpi.ca/ergast/f1"
MIN_INTERVAL = 0.3  # seconds between live requests
_lock = threading.Lock()
_last_request = 0.0


class JolpicaError(RuntimeError):
    pass


def _throttle():
    global _last_request
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


@st.cache_data(ttl=3600, show_spinner=False)
def get(path: str, limit: int = 100, offset: int = 0) -> dict:
    """Fetch `path` (e.g. "current/next") and return the MRData payload."""
    url = f"{BASE_URL}/{path.strip('/')}.json"
    for attempt in range(4):
        _throttle()
        try:
            resp = requests.get(url, params={"limit": limit, "offset": offset}, timeout=15)
        except requests.RequestException as exc:
            if attempt == 3:
                raise JolpicaError(f"Could not reach jolpica-f1: {exc}") from exc
            time.sleep(2**attempt)
            continue
        if resp.status_code == 429:  # rate limited: back off and retry
            time.sleep(2 ** (attempt + 1))
            continue
        if not resp.ok:
            raise JolpicaError(f"jolpica-f1 returned {resp.status_code} for {path}")
        return resp.json()["MRData"]
    raise JolpicaError("jolpica-f1 rate limit hit, try again in a minute")


def races(path: str) -> list[dict]:
    """Return the Races list for a schedule/results path."""
    return get(path)["RaceTable"]["Races"]


def standings(season: str, kind: str, round_: int | None = None) -> dict | None:
    """Return one standings list ({season, round, DriverStandings|ConstructorStandings})
    with every entry, paging past jolpica's 100-row limit. `kind` is "driver" or
    "constructor". Returns None when the season has no standings of that kind."""
    path = f"{season}/{round_}/{kind}standings" if round_ else f"{season}/{kind}standings"
    key = "DriverStandings" if kind == "driver" else "ConstructorStandings"
    page = get(path)
    lists = page["StandingsTable"]["StandingsLists"]
    if not lists:
        return None
    result = lists[0]
    total = int(page.get("total", 0))
    offset = len(result[key])
    while offset < total:
        more = get(path, offset=offset)["StandingsTable"]["StandingsLists"]
        if not more or not more[0][key]:
            break
        result[key] = result[key] + more[0][key]
        offset += len(more[0][key])
    return result


def all_races(path: str, on_page=None) -> list[dict]:
    """Return every race for a results-style `path` (e.g. "results/1"),
    paging through jolpica's 100-row limit. Races split across two pages
    are merged. `on_page(done, total)` is called after each page."""
    merged: dict[tuple, dict] = {}
    offset, total = 0, None
    while total is None or offset < total:
        page = get(path, offset=offset)
        total = int(page.get("total", 0))
        races_ = page["RaceTable"]["Races"]
        rows = 0
        for race in races_:
            key = (race["season"], race["round"])
            results = race.get("Results", [])
            rows += len(results)
            if key in merged:
                merged[key]["Results"] = merged[key]["Results"] + results
            else:
                merged[key] = race
        if on_page:
            on_page(min(offset + max(rows, 1), total), total)
        if rows == 0:
            break
        offset += rows
    return list(merged.values())
