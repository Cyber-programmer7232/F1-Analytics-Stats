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
